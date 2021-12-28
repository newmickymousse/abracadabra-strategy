// SPDX-License-Identifier: AGPL-3.0
pragma solidity 0.6.12;
pragma experimental ABIEncoderV2;

import {BaseStrategy} from "@yearnvaults/contracts/BaseStrategy.sol";
import "@openzeppelin/contracts/math/Math.sol";
import {
    SafeERC20,
    SafeMath,
    IERC20,
    Address
} from "@openzeppelin/contracts/token/ERC20/SafeERC20.sol";

import "./libraries/Boring/BoringMath.sol";
import "./libraries/Boring/BoringRebase.sol";

import "../interfaces/chainlink/AggregatorInterface.sol";
import "../interfaces/swap/ISwap.sol";
import "../interfaces/swap/ICurveFI.sol";
import "../interfaces/yearn/IBaseFee.sol";
import "../interfaces/yearn/IVault.sol";


interface IBentoBoxV1 {
    function balanceOf(IERC20, address) external view returns (uint256);

    function transfer(
        IERC20 token,
        address from,
        address to,
        uint256 share
    ) external;

    function deposit(
        IERC20 token,
        address from,
        address to,
        uint256 amount,
        uint256 share
    ) external payable returns (uint256 amountOut, uint256 shareOut);

    function setMasterContractApproval(
        address user,
        address masterContract,
        bool approved,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external;

    function toAmount(
        IERC20 token,
        uint256 share,
        bool roundUp
    ) external view returns (uint256 amount);

    function toShare(
        IERC20 token,
        uint256 amount,
        bool roundUp
    ) external view returns (uint256 share);

    function totals(IERC20) external view returns (Rebase memory totals_);

    function withdraw(
        IERC20 token_,
        address from,
        address to,
        uint256 amount,
        uint256 share
    ) external returns (uint256 amountOut, uint256 shareOut);
}

interface IAbracadabra {
    function COLLATERIZATION_RATE() external view returns (uint256);

    function bentoBox() external view returns (IBentoBoxV1);

    function masterContract() external view returns (address);

    function addCollateral(
        address to,
        bool skim,
        uint256 share
    ) external;

    function removeCollateral(address to, uint256 share) external;

    function borrow(address to, uint256 amount)
        external
        returns (uint256 part, uint256 share);

    function repay(
        address to,
        bool skim,
        uint256 part
    ) external returns (uint256 amount);

    function exchangeRate() external view returns (uint256);

    function userBorrowPart(address) external view returns (uint256);

    function userCollateralShare(address) external view returns (uint256);

    function totalBorrow() external view returns (Rebase memory totals);

    function collateral() external view returns (address);

    function accrue() external;
}


contract Strategy is BaseStrategy {
    using SafeERC20 for IERC20;
    using Address for address;
    using SafeMath for uint256;


    // Collateral Rate Precision
    uint256 internal constant C_RATE_PRECISION = 1e5;

    // Exchange Rate Precision
    uint256 internal constant EXCHANGE_RATE_PRECISION = 1e18;

    // MIM token
    IERC20 internal constant investmentToken =
        IERC20(0x99D8a9C45b2ecA8864373A26D1459e3Dff1e17F3);

    // 100%
    uint256 internal constant MAX_BPS = C_RATE_PRECISION;

    // Maximum loss on withdrawal from yVault
    uint256 internal constant MAX_LOSS_BPS = 10000;

    // Wrapped Ether - Used for swaps routing
    address internal constant WETH = 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2;

    // DAI - Used for swaps routing
    IERC20 private constant dai =
        IERC20(0x6B175474E89094C44Da98b954EedeAC495271d0F);

    // crvMIM - Used for efficient mim-dai swaps
    ICurveFI private constant crvMIM =
        ICurveFI(0x5a6A4D54456819380173272A5E8E9B9904BdF41B);

    // SushiSwap router
    ISwap internal constant sushiswapRouter =
        ISwap(0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F);

    // Uniswap router
    ISwap internal constant uniswapRouter =
        ISwap(0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D);

    // Provider to read current block's base fee
    IBaseFee internal constant baseFeeProvider =
        IBaseFee(0xf8d0Ec04e94296773cE20eFbeeA82e76220cD549);

    // Use Chainlink oracle to obtain latest want_underlying_token/ETH price
    AggregatorInterface public chainlinkWantUnderlyingTokenToETHPriceFeed;

    // MIM yVault
    IVault public yVault;

    // Want as vault
    IVault internal wantAsVault;

    // Router used for swaps
    ISwap public router;

    // Our desired collaterization ratio
    uint256 public collateralizationRatio;

    // Allow the collateralization ratio to drift a bit in order to avoid cycles
    uint256 public rebalanceTolerance;

    // Max acceptable base fee to take more debt or harvest
    uint256 public maxAcceptableBaseFee;

    // Maximum acceptable loss on withdrawal. Default to 0.01%.
    uint256 public maxLoss;

    // If set to true the strategy will never try to repay debt by selling want
    bool public leaveDebtBehind;

    // Name of the strategy
    string internal strategyName;

    // Abracadabra Contract
    IAbracadabra private abracadabra;

    // BentoBox corresponding to the Abracadabra Contract
    IBentoBoxV1 private bentoBox;

    // Abracadabra max collaterization ratio
    uint256 private maxCollaterizationRate;

    // ----------------- INIT FUNCTIONS TO SUPPORT CLONING -----------------

    constructor(
        address _vault,
        address _yVault,
        string memory _strategyName,
        address _abracadabra,
        address _chainlinkWantUnderlyingTokenToETHPriceFeed
    ) public BaseStrategy(_vault) {
        _initializeThis(
            _yVault,
            _strategyName,
            _abracadabra,
            _chainlinkWantUnderlyingTokenToETHPriceFeed
        );
    }

    function initialize(
        address _vault,
        address _yVault,
        string memory _strategyName,
        address _abracadabra,
        address _chainlinkWantUnderlyingTokenToETHPriceFeed
    ) public {
        // Make sure we only initialize one time
        require(address(yVault) == address(0)); // dev: strategy already initialized

        address sender = msg.sender;

        // Initialize BaseStrategy
        _initialize(_vault, sender, sender, sender);

        // Initialize cloned instance
        _initializeThis(
            _yVault,
            _strategyName,
            _abracadabra,
            _chainlinkWantUnderlyingTokenToETHPriceFeed
        );
    }

    function _initializeThis(
        address _yVault,
        string memory _strategyName,
        address _abracadabra,
        address _chainlinkWantUnderlyingTokenToETHPriceFeed
    ) internal {
        yVault = IVault(_yVault);
        strategyName = _strategyName;

        abracadabra = IAbracadabra(_abracadabra);
        bentoBox = IBentoBoxV1(abracadabra.bentoBox());
        maxCollaterizationRate = MAX_BPS / abracadabra.COLLATERIZATION_RATE() * 100;

        wantAsVault = IVault(address(want));

        chainlinkWantUnderlyingTokenToETHPriceFeed = AggregatorInterface(
            _chainlinkWantUnderlyingTokenToETHPriceFeed
        );

        // Set default router to SushiSwap
        router = sushiswapRouter;

        // Set health check to health.ychad.eth
        healthCheck = 0xDDCea799fF1699e98EDF118e0629A974Df7DF012;

        // Current ratio can drift (collateralizationRatio - rebalanceTolerance, collateralizationRatio + rebalanceTolerance)
        // Allow additional 15% in any direction (210, 240) by default
        rebalanceTolerance = (15 * MAX_BPS) / 100;

        // Use 10% more than the max collateral ratio as target
        collateralizationRatio = (maxCollaterizationRate + (MAX_BPS / 10) );

        // If we lose money in yvMIM then we are not OK selling want to repay it
        leaveDebtBehind = true;

        // Define maximum acceptable loss on withdrawal to be 0.01%.
        maxLoss = 1;

        // Set max acceptable base fee to take on more debt to 60 gwei
        maxAcceptableBaseFee = 60 * 1e9;

        // We need to approve the abracadabra master contract to operate
        bentoBox.setMasterContractApproval(
            address(this),
            abracadabra.masterContract(),
            true,
            0,
            0,
            0
        );

        want.safeApprove(address(bentoBox), type(uint256).max);
        investmentToken.safeApprove(address(bentoBox), type(uint256).max);
        dai.safeApprove(address(uniswapRouter), type(uint256).max);
        investmentToken.safeApprove(address(crvMIM), type(uint256).max);

        require(address(want) == abracadabra.collateral());
    }

    // ----------------- SETTERS & MIGRATION -----------------

    // Maximum acceptable base fee of current block to take on more debt
    function setMaxAcceptableBaseFee(uint256 _maxAcceptableBaseFee)
        external
        onlyEmergencyAuthorized
    {
        maxAcceptableBaseFee = _maxAcceptableBaseFee;
    }

    // Target collateralization ratio to maintain within bounds
    function setCollateralizationRatio(uint256 _collateralizationRatio)
        external
        onlyEmergencyAuthorized
    {
        require(
            _collateralizationRatio.sub(rebalanceTolerance) > maxCollaterizationRate
        ); // dev: desired collateralization ratio is too low
        collateralizationRatio = _collateralizationRatio;
    }

    // Rebalancing bands (collat ratio - tolerance, collat_ratio + tolerance)
    function setRebalanceTolerance(uint256 _rebalanceTolerance)
        external
        onlyEmergencyAuthorized
    {
        require(collateralizationRatio.sub(_rebalanceTolerance) > maxCollaterizationRate); // dev: desired rebalance tolerance makes allowed ratio too low
        rebalanceTolerance = _rebalanceTolerance;
    }

    // Max slippage to accept when withdrawing from yVault
    function setMaxLoss(uint256 _maxLoss) external onlyVaultManagers {
        require(_maxLoss <= MAX_LOSS_BPS); // dev: invalid value for max loss
        maxLoss = _maxLoss;
    }

    // If set to true the strategy will never sell want to repay debts
    function setLeaveDebtBehind(bool _leaveDebtBehind)
        external
        onlyEmergencyAuthorized
    {
        leaveDebtBehind = _leaveDebtBehind;
    }

    // Move yvMIM funds to a new yVault
    function migrateToNewMIMYVault(IVault newYVault) external onlyGovernance {
        uint256 balanceOfYVault = yVault.balanceOf(address(this));
        if (balanceOfYVault > 0) {
            yVault.withdraw(balanceOfYVault, address(this), maxLoss);
        }
        investmentToken.safeApprove(address(yVault), 0);

        yVault = newYVault;
        _depositInvestmentTokenInYVault();
    }

    // Allow switching between Uniswap and SushiSwap
    function switchDex(bool isUniswap) external onlyVaultManagers {
        if (isUniswap) {
            router = uniswapRouter;
        } else {
            router = sushiswapRouter;
        }
    }

    // Allow external debt repayment
    // Attempt to take currentRatio to target c-ratio
    // Passing zero will repay all debt if possible
    function emergencyDebtRepayment(uint256 currentRatio)
        external
        onlyVaultManagers
    {
        _repayDebt(currentRatio);
    }

    // Allow repayment of an arbitrary amount of MIM in case of an emergency
    // Difference with `emergencyDebtRepayment` function above is that here we
    // are short-circuiting all strategy logic and repaying MIM at once
    // This could be helpful if for example yvMIM withdrawals are failing and
    // we want to do a MIM airdrop and direct debt repayment instead
    function repayDebtWithMIMBalance(uint256 amount)
        external
        onlyVaultManagers
    {
        _repayInvestmentTokenDebt(amount);
    }

    // ******** OVERRIDDEN METHODS FROM BASE CONTRACT ************

    function name() external view override returns (string memory) {
        return strategyName;
    }

    function delegatedAssets() external view override returns (uint256) {
        uint256 totalInvestmentToken =
            _valueOfInvestment().add(balanceOfInvestmentTokenInBentoBox()).add(
                balanceOfInvestmentToken()
            );
        return _convertInvestmentTokenToWant(totalInvestmentToken);
    }

    function estimatedTotalAssets() public view override returns (uint256) {
        uint256 remainingCollateral =
            balanceOfCollateralInMIM() == 0
                ? 0
                : balanceOfCollateralInMIM().sub(balanceOfDebt());
        uint256 remainingInvestmentToken =
            _valueOfInvestment()
                .add(balanceOfInvestmentTokenInBentoBox())
                .add(balanceOfInvestmentToken())
                .add(remainingCollateral);

        return balanceOfWant().add(_convertInvestmentTokenToWant(remainingInvestmentToken));
    }

    function prepareReturn(uint256 _debtOutstanding)
        internal
        override
        returns (
            uint256 _profit,
            uint256 _loss,
            uint256 _debtPayment
        )
    {
        uint256 totalDebt = vault.strategies(address(this)).totalDebt;

        // Claim rewards from yVault
        _takeYVaultProfit();

        uint256 totalAssetsAfterProfit = estimatedTotalAssets();

        _profit = totalAssetsAfterProfit > totalDebt
            ? totalAssetsAfterProfit.sub(totalDebt)
            : 0;

        uint256 _amountFreed;
        uint256 _toLiquidate = _debtOutstanding.add(_profit);
        if (_toLiquidate > 0) {
            (_amountFreed, _loss) = liquidatePosition(_toLiquidate);
        }
        _debtPayment = Math.min(_debtOutstanding, _amountFreed);

        if (_loss > _profit) {
            // Example:
            // debtOutstanding 100, profit 50, _amountFreed 100, _loss 50
            // loss should be 0, (50-50)
            // profit should endup in 0
            _loss = _loss.sub(_profit);
            _profit = 0;
        } else {
            // Example:
            // debtOutstanding 100, profit 50, _amountFreed 140, _loss 10
            // _profit should be 40, (50 profit - 10 loss)
            // loss should end up in be 0
            _profit = _profit.sub(_loss);
            _loss = 0;
        }
    }

    function adjustPosition(uint256 _debtOutstanding) internal override {
        if (emergencyExit) {
            return;
        }
        // If we have enough want to deposit more into the abracadara, we do it
        // Do not skip the rest of the function as it may need to repay or take on more debt
        uint256 wantBalance = balanceOfWant();
        if (wantBalance > _debtOutstanding) {
            uint256 amountToDeposit = wantBalance.sub(_debtOutstanding);
            _depositToAbracadabra(amountToDeposit);
        }

        // Allow the ratio to move a bit in either direction to avoid cycles
        uint256 currentRatio = getCurrentCollateralRatio();
        if (currentRatio < collateralizationRatio.sub(rebalanceTolerance)) {
            _repayDebt(currentRatio);
        } else if (
            currentRatio > collateralizationRatio.add(rebalanceTolerance)
        ) {
            _mintMoreInvestmentToken();
        }

        // If we have anything left to invest then deposit into the yVault
        _depositInvestmentTokenInYVault();
    }

    function liquidatePosition(uint256 _amountNeeded)
        internal
        override
        returns (uint256 _liquidatedAmount, uint256 _loss)
    {
        uint256 balance = balanceOfWant();

        // Check if we can handle it without freeing collateral
        if (balance >= _amountNeeded) {
            return (_amountNeeded, 0);
        }

        // We only need to free the amount of want not readily available
        uint256 amountToFree = _amountNeeded.sub(balance);

        uint256 price = _getWantTokenPrice();
        uint256 collateralBalance = balanceOfCollateral();

        // We cannot free more than what we have locked
        amountToFree = Math.min(amountToFree, collateralBalance);

        uint256 totalDebt = balanceOfDebt();

        // If for some reason we do not have debt, make sure the operation does not revert
        if (totalDebt == 0) {
            totalDebt = 1;
        }

        uint256 toFreeIT = amountToFree.mul(price).div(EXCHANGE_RATE_PRECISION);
        uint256 collateralIT = collateralBalance.mul(price).div(EXCHANGE_RATE_PRECISION);
        uint256 newRatio =
            collateralIT.sub(toFreeIT).mul(MAX_BPS).div(totalDebt);

        // Attempt to repay necessary debt to restore the target collateralization ratio
        _repayDebt(newRatio);

        // Unlock as much collateral as possible while keeping the target ratio
        amountToFree = Math.min(amountToFree, _maxWithdrawal());
        _freeCollateralAndRepayMIM(amountToFree, 0);

        // If we still need more want to repay, we may need to unlock some collateral to sell
        if (
            !leaveDebtBehind &&
            balanceOfWant() < _amountNeeded &&
            balanceOfDebt() > 0
        ) {
            _sellCollateralToRepayRemainingDebtIfNeeded();
        }

        uint256 looseWant = balanceOfWant();
        if (_amountNeeded > looseWant) {
            _liquidatedAmount = looseWant;
            _loss = _amountNeeded.sub(looseWant);
        } else {
            _liquidatedAmount = _amountNeeded;
            _loss = 0;
        }
    }

    function liquidateAllPositions()
        internal
        override
        returns (uint256 _amountFreed)
    {
        (_amountFreed, ) = liquidatePosition(estimatedTotalAssets());
    }

    function harvestTrigger(uint256 callCost)
        public
        view
        override
        returns (bool)
    {
        return isCurrentBaseFeeAcceptable() && super.harvestTrigger(callCost);
    }

    function tendTrigger(uint256 callCostInWei)
        public
        view
        override
        returns (bool)
    {
        // Nothing to adjust if there is no collateral locked
        if (balanceOfCollateral() == 0) {
            return false;
        }

        uint256 currentRatio = getCurrentCollateralRatio();

        // If we need to repay debt and are outside the tolerance bands,
        // we do it regardless of the call cost
        if (currentRatio < collateralizationRatio.sub(rebalanceTolerance)) {
            return true;
        }

        // Mint more MIM if possible
        return
            currentRatio > collateralizationRatio.add(rebalanceTolerance) &&
            balanceOfDebt() > 0 &&
            isCurrentBaseFeeAcceptable() &&
            bentoBox.balanceOf(investmentToken, address(abracadabra)) > 0;
    }

    //TODO: fix, not working properly
    function prepareMigration(address _newStrategy) internal override {
        // Move yvMIM balance to the new strategy
        /* collateralizationRatio = 0; */
        /* _withdrawFromYVault(balanceOfCollateralInMIM()); */
        _repayDebt(0);
        _freeCollateralAndRepayMIM(balanceOfCollateral(), 0);

        uint256 _balanceOfMIM = balanceOfInvestmentToken();
        if (_balanceOfMIM > 0) {
            investmentToken.safeTransfer(_newStrategy, _balanceOfMIM);
        }
        if (balanceOfInvestmentTokenInBentoBox() > 0 || bentoBox.balanceOf(want, address(this)) > 0) {
            transferAllBentoBalance(_newStrategy);
        }

        IERC20(yVault).safeTransfer(
            _newStrategy,
            yVault.balanceOf(address(this))
        );
    }

    function protectedTokens()
        internal
        view
        override
        returns (address[] memory ret)
    {
        ret = new address[](3);
        ret[0] = yVault.token();
        ret[1] = wantAsVault.token();
        ret[2] = address(yVault);
    }

    function ethToWant(uint256 _amtInWei)
        public
        view
        virtual
        override
        returns (uint256)
    {
        if (address(want) == address(WETH)) {
            return _amtInWei;
        }

        uint256 price = uint256(chainlinkWantUnderlyingTokenToETHPriceFeed.latestAnswer());
        //TODO: check if this formula is working properly
        return _amtInWei.mul(EXCHANGE_RATE_PRECISION).div(price).mul(wantAsVault.pricePerShare());
    }

    // ----------------- INTERNAL FUNCTIONS SUPPORT -----------------

    function _repayDebt(uint256 currentRatio) internal {
        //need to compute pending interest
        abracadabra.accrue();
        uint256 currentDebt = balanceOfDebt();

        // Nothing to repay if we are over the collateralization ratio
        // or there is no debt
        if (currentRatio > collateralizationRatio || currentDebt == 0) {
            return;
        }

        // ratio = collateral / debt
        // collateral = current_ratio * current_debt
        // collateral amount is invariant here so we want to find new_debt
        // so that new_debt * desired_ratio = current_debt * current_ratio
        // new_debt = current_debt * current_ratio / desired_ratio
        // and the amount to repay is the difference between current_debt and new_debt
        // amountToRepay = (current_debt - new_debt)
        // amountToRepay = (current_debt - (current_debt * current_ratio / desired_ratio))
        // amountToRepay = current_debt * (1 - (current_ratio / desired_ratio))
        /* uint256 newDebt =
            currentDebt.mul(currentRatio).div(collateralizationRatio); */

        uint256 amountToRepay = currentDebt.mul(MAX_BPS.sub(currentRatio.div(collateralizationRatio)));

        // If we sold want to repay debt we will have MIM readily available in the strategy
        // This means we need to count both yvMIM shares, current MIM balance and MIM in bentobox
        uint256 totalInvestmentAvailableToRepay =
            _valueOfInvestment().add(balanceOfInvestmentToken()).add(balanceOfInvestmentTokenInBentoBox());

        amountToRepay = Math.min(totalInvestmentAvailableToRepay, amountToRepay);

        uint256 balanceIT = balanceOfInvestmentToken();
        if (amountToRepay > balanceIT) {
            _withdrawFromYVault(amountToRepay.sub(balanceIT));
        }
        _repayInvestmentTokenDebt(amountToRepay);
    }

    function _sellCollateralToRepayRemainingDebtIfNeeded() internal {
        uint256 currentInvestmentValue = _valueOfInvestment();

        uint256 investmentLeftToAcquire =
            balanceOfDebt().sub(currentInvestmentValue);

        uint256 investmentLeftToAcquireInWant =
            _convertInvestmentTokenToWant(investmentLeftToAcquire);

        if (investmentLeftToAcquireInWant <= balanceOfWant()) {
            _buyInvestmentTokenWithWant(investmentLeftToAcquire);
            _repayDebt(0);
            _freeCollateralAndRepayMIM(balanceOfCollateral(), 0);
        }
    }

    // Mint the maximum MIM possible for the locked collateral
    function _mintMoreInvestmentToken() internal {
        uint256 amount = balanceOfCollateralInMIM();

        uint256 _amountToBorrow =
            amount.mul(MAX_BPS).div(collateralizationRatio).sub(balanceOfDebt());

        // won't be able to borrow more than available supply
        _amountToBorrow = Math.min(
            _amountToBorrow,
            bentoBox.balanceOf(investmentToken, address(abracadabra))
        );

        if (_amountToBorrow == 0) return;

        abracadabra.borrow(
            address(this),
            bentoBox.toShare(investmentToken, _amountToBorrow, false)
        );

        removeMIMFromBentoBox();
    }

    function _withdrawFromYVault(uint256 _amountIT) internal returns (uint256) {
        if (_amountIT == 0) {
            return 0;
        }
        // No need to check allowance because the contract == token
        uint256 balancePrior = balanceOfInvestmentToken();
        uint256 sharesToWithdraw =
            Math.min(
                _investmentTokenToYShares(_amountIT),
                yVault.balanceOf(address(this))
            );
        if (sharesToWithdraw == 0) {
            return 0;
        }
        yVault.withdraw(sharesToWithdraw, address(this), maxLoss);
        return balanceOfInvestmentToken().sub(balancePrior);
    }

    function _depositInvestmentTokenInYVault() internal {
        uint256 balanceIT = balanceOfInvestmentToken();
        if (balanceIT > 0) {
            _checkAllowance(
                address(yVault),
                address(investmentToken),
                balanceIT
            );

            yVault.deposit();
        }
    }

    function _repayInvestmentTokenDebt(uint256 amount) internal {
        if (amount == 0) {
            return;
        }

        uint256 debt = balanceOfDebt();
        uint256 balanceIT = balanceOfInvestmentToken();

        // We cannot pay more than loose balance
        amount = Math.min(amount, balanceIT);

        // We cannot pay more than we owe
        amount = Math.min(amount, debt);

        _checkAllowance(
            address(bentoBox),
            address(investmentToken),
            amount
        );

        if (amount > 0) {
            // Repay debt amount without unlocking collateral
            _freeCollateralAndRepayMIM(0, amount);
        }
    }

    function _checkAllowance(
        address _contract,
        address _token,
        uint256 _amount
    ) internal {
        if (IERC20(_token).allowance(address(this), _contract) < _amount) {
            IERC20(_token).safeApprove(_contract, 0);
            IERC20(_token).safeApprove(_contract, type(uint256).max);
        }
    }

    function _takeYVaultProfit() internal {
        uint256 _debt = balanceOfDebt();
        uint256 _valueInVault = _valueOfInvestment();
        if (_debt >= _valueInVault) {
            return;
        }

        uint256 profit = _valueInVault.sub(_debt);
        uint256 ySharesToWithdraw = _investmentTokenToYShares(profit);
        if (ySharesToWithdraw > 0) {
            yVault.withdraw(ySharesToWithdraw, address(this), maxLoss);

            _sellInvestmentTokenForWant(balanceOfInvestmentToken());
        }
    }

    function _depositToAbracadabra(uint256 amount) internal {
        if (amount == 0) {
            return;
        }
        _checkAllowance(address(bentoBox), address(want), amount);

        // first, we need to deposit collateral in bentoBox
        (uint256 amountOut, uint256 sharesOut) =
                bentoBox.deposit(
                    want,
                    address(this),
                    address(this),
                    amount,
                    0
                );
        // second, we need to add the collateral to abracadabra
        abracadabra.addCollateral(address(this), false, sharesOut);
    }

    // Returns maximum collateral to withdraw while maintaining the target collateralization ratio
    function _maxWithdrawal() internal view returns (uint256) {
        // Denominated in want
        uint256 totalCollateral = balanceOfCollateral();

        // Denominated in investment token
        uint256 totalDebt = balanceOfDebt();

        // If there is no debt to repay we can withdraw all the locked collateral
        if (totalDebt == 0) {
            return totalCollateral;
        }

        uint256 price = _getWantTokenPrice();

        // Min collateral in want that needs to be locked with the outstanding debt
        // Allow going to the lower rebalancing band
        uint256 minCollateral =
            collateralizationRatio
                .sub(rebalanceTolerance)
                .mul(totalDebt)
                .mul(EXCHANGE_RATE_PRECISION)
                .div(price)
                .div(MAX_BPS);

        // If we are under collateralized then it is not safe for us to withdraw anything
        if (minCollateral > totalCollateral) {
            return 0;
        }

        return totalCollateral.sub(minCollateral);
    }

    // ----------------- PUBLIC BALANCES AND CALCS -----------------

    function balanceOfWant() public view returns (uint256) {
        return want.balanceOf(address(this));
    }

    function balanceOfInvestmentToken() public view returns (uint256) {
        return investmentToken.balanceOf(address(this));
    }

    function balanceOfInvestmentTokenInBentoBox() internal view returns (uint256) {
        return bentoBox.balanceOf(investmentToken, address(this));
    }

    function balanceOfCollateralInBentoBox() internal view returns (uint256) {
        return bentoBox.balanceOf(want, address(this));
    }

    function balanceOfDebt() public view returns (uint256 _borrowedAmount) {
        uint256 borrowPart = abracadabra.userBorrowPart(address(this));

        Rebase memory _totalBorrow = abracadabra.totalBorrow();
        _borrowedAmount =
            borrowPart.mul(_totalBorrow.elastic) /
            _totalBorrow.base;

    }

    // Returns collateral balance in the abracadabra in Want
    function balanceOfCollateral() public view returns (uint256 _collateralAmount) {
        _collateralAmount = _convertInvestmentTokenToWant(balanceOfCollateralInMIM());
    }

    // Returns collateral balance in the abracadabra in MIM
    function balanceOfCollateralInMIM() public view returns (uint256 _collateralAmount) {
        _collateralAmount = bentoBox.toAmount(
            want,
            _convertWantToInvestmentToken(abracadabra.userCollateralShare(address(this))),
            false
        );
    }

    // Effective collateralization ratio of the strat
    function getCurrentCollateralRatio() public view returns (uint256 _collateralRate) {
            if (balanceOfDebt() == 0) return 0;
            _collateralRate = balanceOfCollateralInMIM().mul(C_RATE_PRECISION).div(
                balanceOfDebt()
            );
    }

    // Check if current block's base fee is under max allowed base fee
    function isCurrentBaseFeeAcceptable() public view returns (bool) {
        uint256 baseFee;
        try baseFeeProvider.basefee_global() returns (uint256 currentBaseFee) {
            baseFee = currentBaseFee;
        } catch {
            // Useful for testing until ganache supports london fork
            // Hard-code current base fee to 1000 gwei
            // This should also help keepers that run in a fork without
            // baseFee() to avoid reverting and potentially abandoning the job
            baseFee = 1000 * 1e9;
        }

        return baseFee <= maxAcceptableBaseFee;
    }

    // ----------------- INTERNAL CALCS -----------------

    // Returns the price of want in mim ~ usd
    function _getWantTokenPrice() internal view returns (uint256) {
        return abracadabra.exchangeRate();
    }

    function _valueOfInvestment() internal view returns (uint256) {
        return
            yVault.balanceOf(address(this)).mul(yVault.pricePerShare()).div(
                10**yVault.decimals()
            );
    }

    function _investmentTokenToYShares(uint256 amount)
        internal
        view
        returns (uint256)
    {
        return amount.mul(10**yVault.decimals()).div(yVault.pricePerShare());
    }

    function _lockCollateralAndMintMIM(
        uint256 collateralAmount,
        uint256 mimToMint
    ) internal {
        if (mimToMint == 0) return;
        // won't be able to borrow more than available supply
        mimToMint = Math.min(
            mimToMint,
            bentoBox.balanceOf(investmentToken, address(abracadabra))
        );

        abracadabra.borrow(
            address(this),
            bentoBox.toShare(investmentToken, mimToMint, false)
        );

        removeMIMFromBentoBox();
    }

    function _freeCollateralAndRepayMIM(
        uint256 collateralAmount,
        uint256 mimToRepay
    ) internal {
        Rebase memory _totalBorrow = abracadabra.totalBorrow();
        uint256 owed = balanceOfDebt();

        mimToRepay = Math.min(mimToRepay, owed);

        uint256 _amountToDepositInBB =
            mimToRepay.sub(balanceOfInvestmentTokenInBentoBox());

        _amountToDepositInBB = Math.min(_amountToDepositInBB, balanceOfInvestmentToken());

        bentoBox.deposit(
            investmentToken,
            address(this),
            address(this),
            _amountToDepositInBB,
            0
        );

        //repay receives a part, so we need to calculate the part to repay
        uint256 part =
            RebaseLibrary.toBase(
                _totalBorrow,
                Math.min(mimToRepay, balanceOfInvestmentTokenInBentoBox()),
                true
            );

        abracadabra.repay(
            address(this),
            false,
            Math.min(part, abracadabra.userBorrowPart(address(this)))
        );

        // we need to withdraw enough to keep our c-rate

        // min between collateral wanted and the max to withdraw
        uint256 collateralToWithdraw = Math.min(collateralAmount, _maxWithdrawal());

        if (collateralToWithdraw > 0) {
            abracadabra.removeCollateral(
                address(this),
                bentoBox.toShare(
                    want,
                    collateralToWithdraw,
                    true)
                );
            removeCollateralFromBentoBox();
        }

    }

    // ----------------- TOKEN CONVERSIONS -----------------

    //MIM to Want
    function _convertInvestmentTokenToWant(uint256 amount)
        internal
        view
        returns (uint256)
    {
        return amount.div(abracadabra.exchangeRate()).mul(
            EXCHANGE_RATE_PRECISION
        );
    }

    //Want to MIM
    function _convertWantToInvestmentToken(uint256 amount)
        internal
        view
        returns (uint256)
    {
        return amount.mul(abracadabra.exchangeRate()).div(
            EXCHANGE_RATE_PRECISION
        );
    }


    function _getTokenOutPath(address _token_in, address _token_out)
        internal
        pure
        returns (address[] memory _path)
    {
        bool is_weth =
            _token_in == address(WETH) || _token_out == address(WETH);
        _path = new address[](is_weth ? 2 : 3);
        _path[0] = _token_in;

        if (is_weth) {
            _path[1] = _token_out;
        } else {
            _path[1] = address(WETH);
            _path[2] = _token_out;
        }
    }

    function _sellAForB(
        uint256 _amount,
        address tokenA,
        address tokenB
    ) internal {
        if (_amount == 0 || tokenA == tokenB) {
            return;
        }

        _checkAllowance(address(router), tokenA, _amount);
        router.swapExactTokensForTokens(
            _amount,
            0,
            _getTokenOutPath(tokenA, tokenB),
            address(this),
            now
        );
    }

    function _exchangeUsingCrvMIM(
        uint256 _amount,
        int128 tokenA,
        int128 tokenB
    ) internal {
        if (_amount == 0 || tokenA == tokenB) {
            return;
        }

        crvMIM.exchange_underlying(
            tokenA,
            tokenB,
            _amount,
            0
        );

    }

    function _buyInvestmentTokenWithWant(uint256 _amount) internal {
        if (_amount == 0 || address(investmentToken) == address(want)) {
            return;
        }

        //1. unwrap from vault
        uint256 collateral = wantAsVault.withdraw(_amount);

        //2. underlying token -> dai
        _sellAForB(collateral, wantAsVault.token(), address(dai));

        //3. dai -> crvMIM -> mim
        _checkAllowance(address(crvMIM), address(dai), dai.balanceOf(address(this)));
        _exchangeUsingCrvMIM(dai.balanceOf(address(this)), int128(1), int128(0));
    }

    function _sellInvestmentTokenForWant(uint256 _amount) internal {
        if (_amount == 0 || address(investmentToken) == address(want)) {
            return;
        }
        // 1. exchange investment token (mim) for dai using crvMIM pool
        _checkAllowance(address(crvMIM), address(investmentToken), _amount);

        _exchangeUsingCrvMIM(_amount, int128(0), int128(1));

        // 2. sell DAI for wantAsVault token
        _sellAForB(
            dai.balanceOf(address(this)),
            address(dai),
            address(wantAsVault.token())
        );

        // 3. deposit the token into the wantAsVault
        wantAsVault.deposit();
    }


    /*********************** Other Functions ***********************/

    function removeMIMFromBentoBox() internal {
        bentoBox.withdraw(
            investmentToken,
            address(this),
            address(this),
            balanceOfInvestmentTokenInBentoBox(),
            0
        );
    }

    function removeCollateralFromBentoBox() internal {
        bentoBox.withdraw(
            want,
            address(this),
            address(this),
            balanceOfCollateralInBentoBox(),
            0
        );
    }

    function transferAllBentoBalance(address newDestination) internal {
        bentoBox.transfer(
            investmentToken,
            address(this),
            newDestination,
            balanceOfInvestmentTokenInBentoBox()
        );
        bentoBox.transfer(
            want,
            address(this),
            newDestination,
            balanceOfCollateralInBentoBox()
        );
    }
}
