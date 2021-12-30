import pytest

from brownie import chain


def test_direct_transfer_increments_estimated_total_assets(
    strategy, token, token_whale
):
    initial = strategy.estimatedTotalAssets()
    amount = 10 * (10 ** token.decimals())
    token.transfer(strategy, amount, {"from": token_whale})
    assert strategy.estimatedTotalAssets() == initial + amount


def test_direct_transfer_increments_profits(
    vault, strategy, token, token_whale, gov, RELATIVE_APPROX
):
    initialProfit = vault.strategies(strategy).dict()["totalGain"]
    assert initialProfit == 0

    token.approve(vault.address, 2 ** 256 - 1, {"from": token_whale})
    vault.deposit(1000 * (10 ** token.decimals()), {"from": token_whale})
    chain.sleep(1)
    strategy.harvest({"from": gov})

    amount = 5 * (10 ** token.decimals())
    token.transfer(strategy, amount, {"from": token_whale})

    chain.sleep(1)
    strategy.harvest({"from": gov})
    assert (
        pytest.approx(
            vault.strategies(strategy).dict()["totalGain"] / token.decimals(),
            rel=RELATIVE_APPROX,
        )
        == (initialProfit + amount) / token.decimals()
    )


def test_borrow_token_transfer_sends_to_yvault(
    vault, strategy, token, token_whale, borrow_token, borrow_whale, gov
):
    token.approve(vault, 2 ** 256 - 1, {"from": token_whale})
    vault.deposit(1000 * (10 ** token.decimals()), {"from": token_whale})

    chain.sleep(1)
    strategy.harvest({"from": gov})

    amount = 1_000 * (10 ** borrow_token.decimals())
    borrow_token.transfer(strategy, amount, {"from": borrow_whale})

    chain.sleep(1)
    strategy.harvest({"from": gov})
    assert borrow_token.balanceOf(strategy) == 0


def test_borrow_token_transfer_increments_profits(
    vault, strategy, token, token_whale, borrow_token, borrow_whale, gov, abracadabra
):
    token.approve(vault, 2 ** 256 - 1, {"from": token_whale})
    vault.deposit(1000 * (10 ** token.decimals()), {"from": token_whale})

    chain.sleep(1)
    strategy.harvest({"from": gov})

    amount = 10_000 * (10 ** borrow_token.decimals())

    chain.sleep(1)
    chain.mine(1)

    borrow_token.transfer(strategy, amount, {"from": borrow_whale})

    chain.sleep(1)
    chain.mine(1)
    strategy.harvest({"from": gov})

    token_price = abracadabra.exchangeRate()
    transferInWant = amount / token_price

    chain.sleep(60)  # wait a minute!
    chain.mine(1)

    strategy.harvest({"from": gov})
    # account for fees and slippage - our profit should be at least 95% of the transfer in want
    assert vault.strategies(strategy).dict()["totalGain"] > transferInWant * 0.95


def test_deposit_should_not_increment_profits(vault, strategy, token, token_whale, gov):
    initialProfit = vault.strategies(strategy).dict()["totalGain"]
    assert initialProfit == 0

    token.approve(vault, 2 ** 256 - 1, {"from": token_whale})
    vault.deposit(1000 * (10 ** token.decimals()), {"from": token_whale})

    chain.sleep(1)
    strategy.harvest({"from": gov})

    assert vault.strategies(strategy).dict()["totalGain"] == initialProfit


def test_direct_transfer_with_actual_profits(
    vault, strategy, token, token_whale, borrow_token, borrow_whale, yvault, gov
):
    initialProfit = vault.strategies(strategy).dict()["totalGain"]
    assert initialProfit == 0

    token.approve(vault, 2 ** 256 - 1, {"from": token_whale})
    vault.deposit(10000 * (10 ** token.decimals()), {"from": token_whale})

    chain.sleep(1)
    strategy.harvest({"from": gov})

    # send some profit to yvault
    borrow_token.transfer(
        yvault, 20_000 * (10 ** borrow_token.decimals()), {"from": borrow_whale}
    )

    # sleep for a day
    chain.sleep(24 * 3600)
    chain.mine(1)

    # receive a direct transfer
    airdropAmount = 10 * (10 ** token.decimals())
    token.transfer(strategy, airdropAmount, {"from": token_whale})

    # sleep for another day
    chain.sleep(24 * 3600)
    chain.mine(1)

    strategy.harvest({"from": gov})
    assert (
        vault.strategies(strategy).dict()["totalGain"] > initialProfit + airdropAmount
    )
