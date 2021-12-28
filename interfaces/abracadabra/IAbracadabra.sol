// SPDX-License-Identifier: MIT
pragma solidity 0.6.12;

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
