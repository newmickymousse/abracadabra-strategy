import pytest

from brownie import Contract, reverts

def test_migration(
    chain,
    token,
    vault,
    yvault,
    strategy,
    strategist,
    amount,
    Strategy,
    gov,
    user,
    factory,
    price_oracle_eth,
    abracadabra,
    keeper,
    rewards,
    mim_whale,
    mim,
    RELATIVE_APPROX,
):
    # Deposit to the vault and harvest
    token.approve(vault.address, amount, {"from": user})
    vault.deposit(amount, {"from": user})
    chain.sleep(1)
    strategy.harvest({"from": gov})
    assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount

    # migrate to a new strategy
    clone_tx = factory.cloneMIMMinter(
        vault,
        strategist,
        rewards,
        keeper,
        yvault,
        "ClonedStrategy",
        abracadabra,
        price_oracle_eth,
        {"from": strategist},
    )

    new_strategy = Contract.from_abi(
        "Strategy", clone_tx.events["Cloned"]["clone"], strategy.abi
    )

    # update leave debt behind to False
    strategy.updateStrategyParams(
        strategy.maxAcceptableBaseFee(),
        strategy.collateralizationRatio(),
        strategy.rebalanceTolerance(),
        False,
        strategy.maxLoss(),
        True,
        {"from": gov}
        )

    # token.withdraw(2 * (10 ** 18), strategy.address, 10, {"from": strategy})
    # mim.transfer(yvault, 50 * 1e18, {"from": mim_whale})

    prevBalanceOfDebt = strategy.balanceOfDebt()
    prevBalanceOfCollateral = strategy.balanceOfCollateral(False)
    prevEstimatedTotalAssets = strategy.estimatedTotalAssets()
    prevDelegatedAssets = strategy.delegatedAssets()

    vault.migrateStrategy(strategy, new_strategy, {"from": gov})

    # assert False
    chain.sleep(1)
    new_strategy.harvest({"from": gov})


    assert new_strategy.balanceOfCollateral(False) < prevBalanceOfCollateral
    assert new_strategy.balanceOfCollateral(False) > prevBalanceOfCollateral * (1-abracadabra.BORROW_OPENING_FEE()/1e5)
    assert new_strategy.balanceOfDebt() < prevBalanceOfDebt
    assert new_strategy.balanceOfDebt() > prevBalanceOfDebt * (1-abracadabra.BORROW_OPENING_FEE()/1e5)
    assert new_strategy.estimatedTotalAssets() < prevEstimatedTotalAssets
    assert new_strategy.estimatedTotalAssets() > prevEstimatedTotalAssets  * (1-abracadabra.BORROW_OPENING_FEE()/1e5)
    assert new_strategy.delegatedAssets() < prevDelegatedAssets
    assert new_strategy.delegatedAssets() > prevDelegatedAssets  * (1-abracadabra.BORROW_OPENING_FEE()/1e5)
    assert vault.strategies(new_strategy).dict()["totalDebt"] == amount
    assert vault.strategies(strategy).dict()["totalDebt"] == 0
    assert strategy.estimatedTotalAssets() == 0


# def test_yvault_migration(
#     chain,
#     token,
#     vault,
#     strategy,
#     amount,
#     user,
#     gov,
#     yvault,
#     new_dai_yvault,
#     dai,
#     RELATIVE_APPROX,
# ):
#     token.approve(vault.address, amount, {"from": user})
#     vault.deposit(amount, {"from": user})
#     chain.sleep(1)
#     strategy.harvest({"from": gov})
#     assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount
#
#     balanceBefore = yvault.balanceOf(strategy) * yvault.pricePerShare() / 1e18
#
#     strategy.migrateToNewDaiYVault(new_dai_yvault, {"from": gov})
#
#     assert yvault.balanceOf(strategy) == 0
#     assert dai.allowance(strategy, yvault) == 0
#     assert dai.allowance(strategy, new_dai_yvault) == 2 ** 256 - 1
#     assert (
#         pytest.approx(
#             new_dai_yvault.balanceOf(strategy) * new_dai_yvault.pricePerShare() / 1e18,
#             rel=RELATIVE_APPROX,
#         )
#         == balanceBefore
#     )
#     assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == amount
#
#
# def test_yvault_migration_with_no_assets(
#     token, vault, strategy, amount, user, gov, yvault, new_dai_yvault,
# ):
#
#     token.approve(vault.address, amount, {"from": user})
#     vault.deposit(amount, {"from": user})
#
#     assert strategy.estimatedTotalAssets() == 0
#     strategy.migrateToNewDaiYVault(new_dai_yvault, {"from": gov})
#
#     strategy.harvest({"from": gov})
#
#     assert new_dai_yvault.balanceOf(strategy) > 0
#     assert yvault.balanceOf(strategy) == 0
