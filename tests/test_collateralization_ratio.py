import pytest
from brownie import chain, reverts, Wei


def test_lower_target_ratio_should_take_more_debt(
    vault, strategy, token, yvault, amount, user, gov, RELATIVE_APPROX
):
    # Deposit to the vault
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})

    # Harvest 1: Send funds through the strategy
    chain.sleep(1)
    strategy.harvest({"from": gov})

    # Shares in yVault at the current target ratio
    shares_before = yvault.balanceOf(strategy)

    new_ratio_relative = 0.9

    # In default settings this will be 163 * 0.9 = 147
    strategy.updateStrategyParams(
        strategy.maxAcceptableBaseFee(),
        strategy.collateralizationRatio() * new_ratio_relative,
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )

    # Adjust the position
    strategy.tend({"from": gov})

    # Because the target collateralization ratio is lower, more MIM will be minted
    # and deposited into the yvMIM vault
    assert pytest.approx(
        shares_before / new_ratio_relative, rel=RELATIVE_APPROX
    ) == yvault.balanceOf(strategy)


def test_lower_ratio_inside_rebalancing_band_should_not_take_more_debt(
    vault, strategy, token, yvault, amount, user, gov
):
    # Deposit to the vault
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})

    # Harvest 1: Send funds through the strategy
    chain.sleep(1)
    strategy.harvest({"from": gov})

    # Shares in yVault at the current target ratio
    shares_before = yvault.balanceOf(strategy)

    new_ratio = strategy.collateralizationRatio() - strategy.rebalanceTolerance() * 0.99
    strategy.updateStrategyParams(
        strategy.maxAcceptableBaseFee(),
        new_ratio,
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )

    # Adjust the position
    strategy.tend({"from": gov})

    # Because the current ratio is inside the rebalancing band
    # no more MIM will be minted and deposited into the yvMIM vault
    assert shares_before == yvault.balanceOf(strategy)


def test_higher_target_ratio_should_repay_debt(
    vault, strategy, token, yvault, amount, user, gov, RELATIVE_APPROX
):
    # Deposit to the vault
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})

    # Harvest 1: Send funds through the strategy
    chain.sleep(1)
    strategy.harvest({"from": gov})

    # Shares in yVault at the current target ratio
    shares_before = yvault.balanceOf(strategy)

    new_ratio_relative = 1.2

    # In default settings this will be 163 * 1.2 = 195
    strategy.updateStrategyParams(
        strategy.maxAcceptableBaseFee(),
        strategy.collateralizationRatio() * new_ratio_relative,
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )


    # Adjust the position
    strategy.tend({"from": gov})

    # Because the target collateralization ratio is higher, a part of the debt
    # will be repaid to maintain a healthy ratio
    assert pytest.approx(
        shares_before / new_ratio_relative, rel=RELATIVE_APPROX
    ) == yvault.balanceOf(strategy)


def test_higher_ratio_inside_rebalancing_band_should_not_repay_debt(
    vault, strategy, token, yvault, amount, user, gov
):
    # Deposit to the vault
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})

    # Harvest 1: Send funds through the strategy
    chain.sleep(1)
    strategy.harvest({"from": gov})

    # Shares in yVault at the current target ratio
    shares_before = yvault.balanceOf(strategy)

    new_ratio = (
        strategy.collateralizationRatio()
        + strategy.rebalanceTolerance() * 0.99
    )
    strategy.updateStrategyParams(
        strategy.maxAcceptableBaseFee(),
        new_ratio,
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )


    assert strategy.tendTrigger(1) == False

    # Adjust the position
    strategy.tend({"from": gov})

    # Because the current ratio is inside the rebalancing band no debt will be repaid
    assert shares_before == yvault.balanceOf(strategy)


def test_vault_ratio_calculation_on_withdraw(
    vault, strategy, token, yvault, amount, user, gov, RELATIVE_APPROX
):
    # Initial ratio is 0 because there is no collateral locked
    assert strategy.getCurrentCollateralRatio() == 0

    # Deposit to the vault and send funds through the strategy
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})
    chain.sleep(1)
    strategy.harvest({"from": gov})

    # Collateral ratio should be the target ratio set
    assert (
        pytest.approx(strategy.getCurrentCollateralRatio(), rel=RELATIVE_APPROX)
        == strategy.collateralizationRatio()
    )

    shares_before = yvault.balanceOf(strategy)

    # Withdraw 3% of the assets
    vault.withdraw(amount * 0.03, {"from": user})

    # Strategy should restore collateralization ratio to target value on withdraw
    assert (
        pytest.approx(strategy.collateralizationRatio(), rel=RELATIVE_APPROX)
        == strategy.getCurrentCollateralRatio()
    )

    # Strategy has less funds to invest
    assert pytest.approx(yvault.balanceOf(strategy), rel=RELATIVE_APPROX) == (
        shares_before * 0.97
    )


def test_tend_trigger_conditions(
    vault, strategy, token, token_whale, amount, user, gov
):
    # Initial ratio is 0 because there is no collateral locked
    assert strategy.tendTrigger(1) == False

    # Deposit to the vault and send funds through the strategy
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})
    chain.sleep(1)
    strategy.harvest({"from": gov})

    orig_target = strategy.collateralizationRatio()
    rebalance_tolerance = strategy.rebalanceTolerance()

    # Make sure we are in equilibrium
    assert strategy.tendTrigger(1) == False

    # Going under the rebalancing band should need to adjust position
    # regardless of the max acceptable base fee
    strategy.updateStrategyParams(
        strategy.maxAcceptableBaseFee(),
        orig_target + rebalance_tolerance * 1.01,
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )

    strategy.updateStrategyParams(
        0,
        strategy.collateralizationRatio(),
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )
    assert strategy.tendTrigger(1) == True

    strategy.updateStrategyParams(
        1001 * 1e9,
        strategy.collateralizationRatio(),
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )
    assert strategy.tendTrigger(1) == True

    # Going over the target ratio but inside rebalancing band should not adjust position
    strategy.updateStrategyParams(
        strategy.maxAcceptableBaseFee(),
        orig_target + rebalance_tolerance * 0.99,
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )
    assert strategy.tendTrigger(1) == False

    # Going over the rebalancing band should need to adjust position
    # but only if block's base fee is deemed to be acceptables
    strategy.updateStrategyParams(
        strategy.maxAcceptableBaseFee(),
        orig_target - rebalance_tolerance * 1.01,
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )

    # Max acceptable base fee is set to 1000 gwei for testing, so go just
    # 1 gwei above and 1 gwei below to cover both sides
    strategy.updateStrategyParams(
        1001 * 1e9,
        strategy.collateralizationRatio(),
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )
    assert strategy.tendTrigger(1) == True

    strategy.updateStrategyParams(
        1000 * 1e9,
        strategy.collateralizationRatio(),
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )
    assert strategy.tendTrigger(1) == True

    strategy.updateStrategyParams(
        999 * 1e9,
        strategy.collateralizationRatio(),
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )
    assert strategy.tendTrigger(1) == False

    # Going over the target ratio but inside rebalancing band should not adjust position
    strategy.updateStrategyParams(
        1001 * 1e9,
        orig_target - rebalance_tolerance * 0.99,
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )
    assert strategy.tendTrigger(1) == False

    token.approve(vault.address, 2 ** 256 - 1, {"from": token_whale})
    vault.deposit(Wei("10_000 ether"), {"from": token_whale})

    # Send the funds through the strategy to invest
    chain.sleep(1)
    strategy.setDoHealthCheck(False, {"from": gov})
    strategy.harvest({"from": gov})

    assert strategy.tendTrigger(1) == False


def test_ratio_lower_than_liquidation_should_revert(strategy, gov, abracadabra):
    with reverts():
        strategy.updateStrategyParams(
            strategy.maxAcceptableBaseFee(),
            1e5*10000/abracadabra.COLLATERIZATION_RATE()-100,
            strategy.rebalanceTolerance(),
            strategy.leaveDebtBehind(),
            strategy.maxLoss(),
            True, {"from": gov}
            )


def test_ratio_over_liquidation_but_with_tolerance_under_it_should_revert(
    strategy, gov, abracadabra
):
    strategy.updateStrategyParams(
        strategy.maxAcceptableBaseFee(),
        1e5*10000/abracadabra.COLLATERIZATION_RATE()+strategy.rebalanceTolerance()+100,
        strategy.rebalanceTolerance(),
        strategy.leaveDebtBehind(),
        strategy.maxLoss(),
        True, {"from": gov}
        )

    with reverts():
        strategy.updateStrategyParams(
            strategy.maxAcceptableBaseFee(),
            1e5*10000/abracadabra.COLLATERIZATION_RATE()-strategy.rebalanceTolerance(),
            strategy.rebalanceTolerance(),
            strategy.leaveDebtBehind(),
            strategy.maxLoss(),
            True, {"from": gov}
            )


def test_rebalance_tolerance_under_liquidation_ratio_should_revert(strategy, gov):
    with reverts():
        strategy.updateStrategyParams(
            strategy.maxAcceptableBaseFee(),
            strategy.getCurrentCollateralRatio(),
            strategy.rebalanceTolerance()*2,
            strategy.leaveDebtBehind(),
            strategy.maxLoss(),
            True, {"from": gov}
            )
