from brownie import chain, reverts


def test_high_profit_causes_healthcheck_revert(
    vault, strategy, token, token_whale, gov, healthCheck
):
    profitLimit = healthCheck.profitLimitRatio()
    maxBPS = 10_000

    # Send some funds to the strategy
    token.approve(vault.address, 2 ** 256 - 1, {"from": token_whale})
    vault.deposit(1000 * (10 ** token.decimals()), {"from": token_whale})
    chain.sleep(1)
    strategy.harvest({"from": gov})

    token.transfer(
        strategy,
        vault.strategies(strategy).dict()["totalDebt"] * ((profitLimit + 5) / maxBPS),
        {"from": token_whale},
    )
    chain.sleep(1)
    with reverts("!healthcheck"):
        strategy.harvest({"from": gov})


def test_profit_under_max_ratio_does_not_revert(
    vault, strategy, token, token_whale, gov, healthCheck
):
    profitLimit = healthCheck.profitLimitRatio()
    maxBPS = 10_000

    # Send some funds to the strategy
    token.approve(vault.address, 2 ** 256 - 1, {"from": token_whale})
    vault.deposit(1000 * (10 ** token.decimals()), {"from": token_whale})
    chain.sleep(1)
    strategy.harvest({"from": gov})

    token.transfer(
        strategy,
        vault.strategies(strategy).dict()["totalDebt"] * ((profitLimit - 5) / maxBPS),
        {"from": token_whale},
    )
    chain.sleep(1)
    strategy.harvest({"from": gov})

    # If we reach the assert the harvest did not revert
    assert True
