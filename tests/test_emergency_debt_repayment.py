import pytest
from brownie import chain, reverts, Wei

DUST_THRESHOLD = 10_000

def test_passing_zero_should_repay_all_debt(
    vault, strategy, token, token_whale, user, gov, mim, mim_whale, yvMIM, RELATIVE_APPROX
):
    amount = 10_000 * (10 ** token.decimals())

    # Deposit to the vault
    token.approve(vault.address, amount, {"from": token_whale})
    vault.deposit(amount, {"from": token_whale})

    # Send funds through the strategy
    chain.sleep(1)
    strategy.harvest({"from": gov})
    assert strategy.balanceOfDebt() > 0

    # Send some profit to yVault
    mim.transfer(yvMIM, yvMIM.totalAssets() * 0.001, {"from": mim_whale})

    # Harvest 2: Realize profit
    # strategy.setDoHealthCheck(False, {"from":gov})
    tx = strategy.harvest({"from": gov})
    # print(tx.events['StrategyReported'])

    chain.sleep(3600 * 6)  # 6 hrs needed for profits to unlock
    chain.mine(1)

    prev_collat = strategy.balanceOfCollateral(False)
    strategy.emergencyDebtRepayment(0, 0, {"from": vault.management()})
    # assert False

    # All debt is repaid and collateral is left untouched
    assert strategy.balanceOfDebt() < DUST_THRESHOLD
    assert strategy.balanceOfCollateral(False) == prev_collat


def test_passing_value_over_collat_ratio_does_nothing(
    vault, strategy, token, amount, user, gov
):
    # Deposit to the vault
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})

    # Send funds through the strategy
    chain.sleep(1)
    strategy.harvest({"from": gov})
    assert strategy.balanceOfDebt() > 0

    prev_debt = strategy.balanceOfDebt()
    prev_collat = strategy.balanceOfCollateral(False)
    c_ratio = strategy.collateralizationRatio()
    strategy.emergencyDebtRepayment(0, c_ratio + 1, {"from": vault.management()})

    # Debt and collat remain the same
    assert strategy.balanceOfDebt() == prev_debt
    assert strategy.balanceOfCollateral(False) == prev_collat


def test_from_ratio_adjusts_debt(
    vault, strategy, token, amount, user, gov, RELATIVE_APPROX
):
    # Deposit to the vault
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})

    # Send funds through the strategy
    chain.sleep(1)
    strategy.harvest({"from": gov})
    assert strategy.balanceOfDebt() > 0

    prev_debt = strategy.balanceOfDebt()
    prev_collat = strategy.balanceOfCollateral(False)
    c_ratio = strategy.collateralizationRatio()
    prev_collat_ratio = strategy.getCurrentCollateralRatio()
    strategy.emergencyDebtRepayment(0, c_ratio * 0.7, {"from": vault.management()})

    # Debt is partially repaid and collateral is left untouched
    assert strategy.balanceOfDebt() < prev_debt
    assert strategy.balanceOfCollateral(False) == prev_collat
    assert strategy.balanceOfDebt() > DUST_THRESHOLD
    assert strategy.getCurrentCollateralRatio() > prev_collat_ratio

    assert (
        pytest.approx(strategy.balanceOfDebt(), rel=RELATIVE_APPROX) == prev_debt * 0.7
    )
