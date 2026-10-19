"""Notifier loops: one run each, against fakes."""
import subject

# 2500 copper per gem: 400 gems cost 100 gold
PRICE = (200, {"coins_per_gem": 2500, "quantity": 4000})


async def test_gem_tracker_notifies_once_the_price_drops():
    sent, writes, error = await subject.run_gem_tracker([PRICE], {1: 1_100_000, 2: 900_000})
    assert error is None
    assert sent == [(1, "Hey, <@1>! You asked to be notified when 400 gems were cheaper than 110 gold . "
                        "Guess what? They're now only 100 gold !")]
    # Notified users stop tracking; the other keeps waiting
    assert writes == [(1, "set", {"gemtrack": None})]


async def test_gem_tracker_survives_api_errors(caplog):
    # discord.py stops a task loop for good on any exception but network
    # errors, so a bad API response must not escape
    sent, writes, error = await subject.run_gem_tracker([(500, {"text": "error"})], {1: 1_100_000})
    assert error is None
    assert sent == writes == []
    assert "Couldn't check the gem price" in caplog.text
