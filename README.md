# GW2Bot

An extension to [Toothy](https://github.com/Maselkov/Toothy).

[Invite the public bot to your Discord Server!](https://discord.com/api/oauth2/authorize?client_id=310050883100737536&permissions=939879488&scope=bot%20applications.commands)

## How To Run

First you must install Toothy by following the [Toothy setup instructions](https://github.com/Maselkov/Toothy/blob/master/README.md).

Then clone GW2Bot into the `cogs` directory of Toothy and install the dependencies:
```bash
# Go to Toothy directory
cd path/to/Toothy

# Clone GW2Bot into the cogs directory
git clone https://github.com/Maselkov/GW2Bot.git ./cogs

# Go to cogs directory
cd cogs

# Activate the Toothy virtual environment you set up with Toothy
source ~/.venvs/toothyenv/bin/activate # POSIX
source ~/.venvs/toothyenv/Scripts/activate # Windows

# Install GW2Bot dependencies
pip install -r requirements.txt
```

Now run Toothy. Note: The default prefix is `>` but you can change this in your `config.json` file.

While Toothy is running, send a direct message via Discord to your Toothy bot to load the GW2Bot extension:
```bash
>load guildwars2
```

After the GW2Bot extension has loaded successfully, send another direct message to your Toothy bot to sync the command tree:
```bash
>sync
```

Now you should be able to use slash commands with your Toothy bot in your Discord server!

## Feature List

* [Persistent storage of API keys](https://i.imgur.com/m82tUfW.png)
* [Search your account for items](https://i.imgur.com/xt1K62h.png)
* [Automatic game update notifications](https://i.imgur.com/Knq0KYd.png)
* [Legendary Insight count](https://i.imgur.com/XCPA4F4.png)
* [Weekly raid progression table](https://i.imgur.com/JLXRcfe.png)

### Character Stuff:

* [Character info](https://i.imgur.com/V2H4xKb.png)
* [Character list](https://i.imgur.com/jjR5rk9.png)
* [Character gear](https://i.imgur.com/ebRQAVy.png)

### PvP Stuff:

* [Account Stats](https://i.imgur.com/GYouG2j.png)
* [General profession stats](https://i.imgur.com/sptENJA.png)
* [Specific profession stats!](https://i.imgur.com/NQwM9Sx.png)

### Misc

* [Account info](https://i.imgur.com/FXev4g6.png)
* [Skill info](https://i.imgur.com/Qp7H3KO.png)
* [WvW info](https://i.imgur.com/vCetQbN.png)
* [Achievement info](https://i.imgur.com/EZWaLDZ.png)
* [Wallet commands](https://i.imgur.com/qbxsbHQ.png)
* [Guild commands](https://i.imgur.com/qBBG8CF.png) - courtesy of @n1tr0-5urf3r
* [Current TP transactions](https://i.imgur.com/UXD6MEf.png) - courtesy of @n1tr0-5urf3r
* [Dailies](https://i.imgur.com/RTc0NAa.png)
* [Wiki search](https://i.imgur.com/Uc7j0eb.png)
* [Gem price](https://i.imgur.com/3oWPYOX.png)
* [Event timer](https://i.imgur.com/h4xrOAE.png)

... and more! You can see all available commands on [the GW2Bot website.](https://gw2bot.info/commands)


## Licensed Works Used
[gw2-fotm-instabilities](https://github.com/Invisi/gw2-fotm-instabilities) by @Invisi which is licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)
