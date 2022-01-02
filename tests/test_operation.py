import pytest

from brownie import reverts, Contract


def test_operation(chain, token, vault, strategy, user, amount, gov, RELATIVE_APPROX):
    # Deposit to the vault
    user_balance_before = token.balanceOf(user)
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})
    assert token.balanceOf(vault.address) == amount

    # harvest
    chain.sleep(1)
    strategy.harvest({"from": gov})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount*(1-1/strategy.collateralizationRatio()*0.05)

    # tend()
    strategy.tend({"from": gov})
    # withdrawal
    vault.withdraw(vault.balanceOf(user), user, 10, {"from": user})#0.1% loss

    assert token.balanceOf(user) < user_balance_before
    assert token.balanceOf(user) > user_balance_before * 0.99

def test_emergency_exit(
    chain, token, vault, strategy, user, amount, gov, RELATIVE_APPROX
):
    # Deposit to the vault
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})
    chain.sleep(1)
    strategy.harvest({"from": gov})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount*(1-1/strategy.collateralizationRatio()*0.05)

    # set emergency and exit
    strategy.setEmergencyExit({"from": gov})
    chain.sleep(1)

    strategy.setDoHealthCheck(False, {"from": gov}) # has losses for the borrow fee
    strategy.harvest({"from": gov})

    assert strategy.estimatedTotalAssets() < amount


def test_profitable_harvest(
    chain,
    token,
    vault,
    mim,
    mim_whale,
    new_mim_yvault,
    strategy,
    user,
    amount,
    gov,
    RELATIVE_APPROX,
):

    # Deposit to the vault
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})
    assert token.balanceOf(vault.address) == amount

    # Harvest 1: Send funds through the strategy
    chain.sleep(1)
    strategy.harvest({"from": gov})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount*(1-1/strategy.collateralizationRatio()*0.05)

    chain.sleep(3600)
    chain.mine(1)

    # Simulate profit in yVault
    before_pps = vault.pricePerShare()
    mim.transfer(new_mim_yvault, new_mim_yvault.totalAssets() * 0.01, {"from": mim_whale})

    # Harvest 2: Realize profit
    strategy.harvest({"from": gov})

    chain.sleep(3600)
    chain.mine(1)
    profit = token.balanceOf(vault.address)  # Profits go to vault

    assert strategy.estimatedTotalAssets() + profit > amount
    assert vault.pricePerShare() > before_pps
    assert vault.totalAssets() > amount


def test_change_debt(chain, gov, token, vault, strategy, user, amount, RELATIVE_APPROX):
    # Deposit to the vault and harvest
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})
    vault.updateStrategyDebtRatio(strategy.address, 5_000, {"from": gov})
    chain.sleep(1)
    strategy.harvest({"from": gov})
    half = int(amount / 2)

    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == half*(1-1/strategy.collateralizationRatio()*0.05)

    vault.updateStrategyDebtRatio(strategy.address, 10_000, {"from": gov})
    chain.sleep(1)
    strategy.harvest({"from": gov})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount*(1-1/strategy.collateralizationRatio()*0.05)

    vault.updateStrategyDebtRatio(strategy.address, 5_000, {"from": gov})
    chain.sleep(1)
    strategy.harvest({"from": gov})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == half*(1-1/strategy.collateralizationRatio()*0.05)


def test_sweep(
    gov, vault, strategy, token, user, amount
):
    # Strategy want token doesn't work
    token.transfer(strategy, amount, {"from": user})
    assert token.address == strategy.want()
    assert token.balanceOf(strategy) > 0
    with reverts("!want"):
        strategy.sweep(token, {"from": gov})

    # Vault share token doesn't work
    with reverts("!shares"):
        strategy.sweep(vault.address, {"from": gov})


def test_triggers(chain, gov, vault, strategy, token, amount, user):
    # Deposit to the vault and harvest
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})
    vault.updateStrategyDebtRatio(strategy.address, 5_000, {"from": gov})
    chain.sleep(1)
    strategy.harvest({"from": gov})

    strategy.harvestTrigger(0)
    strategy.tendTrigger(0)
