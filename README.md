My attempt at making an alternative to that chat that roblox uses.
Uses PyQt6 (And as such, is AGPL licence)

# Downloading and Usage
If you are on windows, it is pretty much just:
1. download the executable
2. open roblox
3. open the executable
4. You are ready to chat

If you are on linux, You must download the required libaries for python (and goes without saying, you need python, I tested with python 3.11):
`PyQt6`  
`httpx`  
`websockets`  
`keyboard` (optional)  
and then download source.py

## Downloading from source via `uv`
To download the project via `uv`, run:
```bash
git clone https://github.com/Hermivore8151/RobloxChatAlternative
cd RobloxChatAlternative
uv sync
uv tool install .
```

If `uv` shows a warning about the PATH variable, follow `uv`'s instructions (it should advise running `uv tool update-shell`), and restart your shell.

Please keep in mind, `uv tool update-shell` may not always work on Windows. If that's the case for you, see the workaround mentioned in https://github.com/astral-sh/uv/issues/17331.

# Verification
To verify, put the code you are given in the banner in your roblox bio somewhere (it can be removed after verification)
You can edit your bio by going to your roblox profile.

Verifying gives you access to votekick people, and removes the red background of your name. Indicating you are who you say.
It also means that your messages will not be hidden if someone else has the toggle to hide other users.

# Safety
So, I'm a one man army, And as such, I cannot moderate these chats. So I leave that to you, with the power of votekicks!
You can initiate a votekick by running `/votekick [username]` which will require half of the members in the lobby to accept it to votekick the person
There is no filters on messages, this is by choice. If you would like filters on the chats for your viewing pleasure, it would however not be hard to add to the client
Create an issue if you would like this.

Rate-limits are enforced on the server, to help prevent spamming.

As for your data in transfer, it uses a WSS under the hood during messaging, and HTTPS for verification, meaning that it is end-to-end encrypted

If you want to hopefully get automod in the near future, you can help me with donations:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/L3L71K5ZBB)

# Features
Now, the interesting part, features:
1. Themes!
  Light and dark themes are provided for your view pleasure. If you are running it from source, you could also add more themes!
  There is also support for a compact mode, that shows more messages per screen space, for those of you that like all the data
  And the window is resizable (which was harder than it seems, thanks windows)

3. Verification system
   Helps you identify if the person talking is who they say they are, If a user is un-verified, they will have a red background on their name.

4. Votekicks
   As mentioned above, since I can't easily moderate, I provide you with votekicks, so that if you spot a bad actor, you can deal with them yourself, without relying on an automated system!

5. Blocking and hiding
   Since obviously, this could provide a way for not-so-nice people to talk to you, as well as votekicks, The client also allows you to hide unverified people from your view, and add users to a block list, which means you cannot see what they say.

6. Hotkeys
   To allow for easy usage, you can bind a hotkey (I personally bound Shift + .) to focus the chat without having to click on it, and also features some neat auto-hiding features.
   Minimising the application will send it to the task tray, and closing it, will, obviously, close it.

7. Support
   Support for **FLATPAK** (yes, linux support!) sober. If you install separately, you may have to set an override for the log directory (in settings)
   As for installation on linux, see `Downloading and Usage`


The UI is pretty simple, here is the settings menu and the chat next to it, with text present:
<img width="900" height="817" alt="{3B8B7131-82BA-4696-BBEF-04477CF673AF}" src="https://github.com/user-attachments/assets/c83ca8b5-daa1-4993-8286-bf7b604da873" />

# The boring parts
For the adept that read the source code, you may realise that this fires API requests off to my API for the chat, which means that there must be a privacy policy and terms of usage
To which there is, or atleast partially
The ToS for my webserver itself can be found at: https://hermivore.cat/tos
And as for data stored, there is non. Your IP is stored in memory to help enforce ratelimits, and messages are also stored in memory with relevant identifiers, however none of it is written to disk
Your IP and messages sent are removed from memory once the chatroom you was in has been emptied, or 100 messages have passed since your last message.

Usage of the program infers acceptance of these terms.
If you want to make your own client, feel free. This software is AGPL, but the API itself is pretty much free use.
Happy messaging!

As for the usage of AI, since that seems to be what people want to know, the UI components and widgets are AI assisted, since I suck at UI, however the logic and the webserver that handles all of the data is hand written, with little to no AI usage. If AI was used, it was most likely for research.

If you need support or want information, message me on discord: `@hermivore`  
or join my server: https://discord.gg/7AY23zTMn7
