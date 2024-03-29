"""
BABBLE BOT

Python script for a Discord bot that facilitates reading challenges. Bot can be added to any Discord server and interacted with via commands.

Commands include: /babble, /join, /drop, /progress, /participants, /timer, /end, /help. Commands must be preceded by a forward slash.

/babble: Starts a reading challenge.
    The user can specify the start time and duration of the challenge.
    If no parameters are provided, the default start time is 1 minute and the default duration is 30 minutes.
/join: Allows a user to join the current reading challenge.
    The user can supply an optional parameter to indicate their initial progress in the session.
    If no parameter is provided, the user will start at page 0.
/drop: Allows a user to drop out of the current reading challenge.
    The user can supply an optional parameter to drop out quietly, which will not send a message to the channel when they drop out.
/progress: Allows a user to update their progress in the current session.
/participants: Lists all the participants in the reading challenge.
/timer: Checks the time left in the current phase, which can be:
    - the time left until the session starts
    - the time left in the session
    - the time left to submit progress after a reading challenge ends
/end: Ends the current session.
/help: Lists all the commands and their usage.

Hosted on Disboard for 24/7 uptime.

Last updated: August 14 2023

"""

import os
import asyncio
import discord
import datetime
from discord.ext import commands
from dotenv import load_dotenv
from typing import Tuple
import traceback

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='/', intents=intents, help_command=None)

all_participants = {}
progress_submitted = {}
babble_active = None           
session_started = None
start_in = 0
duration = 30
start_time = None
end_time = None
session_sleep_task = None
start_sleep_task = None
submit_end_time = None

DEFAULT_START_IN = 1
DEFAULT_DURATION = 30


@bot.event
async def on_ready():
    bot.add_command(babble)
    bot.add_command(join)
    bot.add_command(drop)
    bot.add_command(progress)
    bot.add_command(help)
    bot.add_command(participants)
    print(f'Logged in as {bot.user.name}')


@bot.command()
async def babble(ctx, *, params: str = "1 30"):
    global babble_active, session_started, all_participants, progress_submitted, start_in, duration, start_time, end_time, start_sleep_task, session_sleep_task, submit_end_time
    if not babble_active:
        try:
            babble_active = datetime.datetime.now()
            start_in, duration = parse_babble_params(params)
            start_time = datetime.datetime.now() + datetime.timedelta(minutes=start_in)
            end_time = start_time + datetime.timedelta(minutes=duration)
            submit_end_time = None 

            await send_babble_start_message(ctx, start_in, duration)

            all_participants = {}
            progress_submitted = {}
            start_sleep_task = asyncio.create_task(asyncio.sleep(start_in * 60))
            await start_sleep_task

            await send_babble_session_started_message(ctx)

            session_started = datetime.datetime.now()
            session_sleep_task = asyncio.create_task(asyncio.sleep(duration * 60))
            await session_sleep_task

            await send_babble_end_message(ctx)

            babble_active, session_started = None, None
            start_sleep_task, session_sleep_task = None, None
        except Exception as e:
            await ctx.send(f"An error occurred while executing the babble command: {e}")
            print(traceback.format_exc())
    else:
        await ctx.send('There is already an active reading challenge.')


@bot.command()
async def join(ctx, *initial_progress):
    """
    Allows a user to join the current reading session. The user can supply an optional parameter 
    to indicate their initial progress in the session.
    """
    global babble_active, all_participants, progress_submitted
    if babble_active is not None:
        if ctx.author not in all_participants:
            all_participants[ctx.author] = {'initial': 0, 'current': 0}
            progress_submitted[ctx.author] = False
            initial_progress = " ".join(initial_progress) 

            page_number = 0
            if initial_progress:
                if initial_progress.startswith('pg:'):
                    page = initial_progress[3:].lstrip()
                elif initial_progress.startswith('pg '):
                    page = initial_progress[2:].lstrip()
                elif initial_progress.startswith('pg'):
                    page = initial_progress[2:].lstrip()
                else:
                    page = initial_progress

                if page.isdigit():
                    page_number = int(page)
                    all_participants[ctx.author] = {'initial': page_number, 'current': page_number}
                else:
                    del all_participants[ctx.author]
                    del progress_submitted[ctx.author]
                    await ctx.send(f'The initial progress provided is not a valid page number. Please try joining again. Use /help for more information.')
                    return

            await ctx.send(f'{ctx.author.mention} has joined the reading challenge! Starting at: page {page_number}')
        else:
            await ctx.send(f'You\'re already participating in the reading challenge! If you\'d like to update your progress, use the /drop command and then rejoin the challenge.')
    else:
        await ctx.send('There is no active reading challenge.')



@bot.command()
async def end(ctx):
    """
    Function to end the current session. Will clear the participants list and set babble_active and session_started to None.
    """
    global babble_active, session_started, start_sleep_task, session_sleep_task, all_participants, progress_submitted, end_time, start_time
    if babble_active is not None:
        babble_active, session_started = None, None
        end_time, start_time = None, None
        start_sleep_task.cancel()
        if session_sleep_task is not None:  
            session_sleep_task.cancel()
        
        all_participants.clear()
        progress_submitted.clear()

        await ctx.send(f"The reading challenge has been ended!")
    else:
        await ctx.send('There is no active reading challenge.')


@bot.command()
async def drop(ctx, mode: str = ''):
    """
    Function for the user to drop out of the current session. 
    User can supply an optional parameter to drop out quietly, which will not send a message to the channel when they drop out.
    """
    global babble_active, all_participants, progress_submitted
    if babble_active is not None:
        if ctx.author in all_participants:
            del all_participants[ctx.author]
            del progress_submitted[ctx.author]
            if mode == 'quietly':
                return
            await ctx.send(f'**{ctx.author.mention} has dropped out of the reading challenge.** Rejoin at any time with the `/join` command.')
        else:
            await ctx.send(f'{ctx.author.mention}, you\'re not currently participating in the reading challenge. Join us by using the `/join` command!')
    else:
        await ctx.send('There is no active reading challenge.')


@bot.command()
async def timer(ctx):
    """
    Function to check the time left in the current session. 
    Will print the time left in the session if the session has started. Otherwise, will print the time left until the session starts.
    """
    global end_time, start_time, babble_active, session_started, submit_end_time
    now = datetime.datetime.now()
    
    if babble_active is not None:
        if session_started is None:
            time_left = start_time - now
            minutes = time_left.seconds // 60
            seconds = time_left.seconds % 60
            await ctx.send(f"The session will start in {minutes} minutes and {seconds} seconds.")
        elif not submit_end_time:
            time_left = end_time - now
            minutes = time_left.seconds // 60
            seconds = time_left.seconds % 60
            await ctx.send(f"The session will end in {minutes} minutes and {seconds} seconds. Good luck!")
        else:
            time_left = submit_end_time - now
            minutes = time_left.seconds // 60
            seconds = time_left.seconds % 60
            await ctx.send(f"Time left to submit your progress: {minutes} minutes and {seconds} seconds.")
    elif submit_end_time and now <= submit_end_time:
        time_left = submit_end_time - now
        minutes = time_left.seconds // 60
        seconds = time_left.seconds % 60
        await ctx.send(f"Time left to submit your progress: {minutes} minutes and {seconds} seconds.")
    else:
        await ctx.send("There is no active reading challenge.")



@bot.command()
async def participants(ctx):
    """
    Lists all the participants in the reading challenge.
    """
    global all_participants
    if all_participants:
        participants_list = "\n".join(member.display_name for member in all_participants.keys())
        await ctx.send(f"Participants:\n{participants_list}")
    else:
        await ctx.send("There are no participants in the reading challenge.")


@bot.command()
async def progress(ctx, *, progress: str):
    """
    Command for the user to update their progress in the current session. 
    """
    global all_participants, progress_submitted, session_started
    if session_started is not None:
        if ctx.author in all_participants:
            if progress:
                if progress.startswith('pg:'):
                    page = progress[3:].lstrip()
                elif progress.startswith('pg '):
                    page = progress[2:].lstrip()
                else:
                    page = progress

                if page.isdigit():
                    page_number = int(page)
                    all_participants[ctx.author]['current'] = page_number
                    progress_submitted[ctx.author] = True
                    await ctx.send(f'{ctx.author.mention} has updated their progress to: page {all_participants[ctx.author]["current"]}')
                else:
                    await ctx.send(f'The progress provided is not a valid page number. Please try updating again.')
            else:
                await ctx.send('Please provide your progress in the format `/progress pg X` or `/progress X`, where X is the page number.')
        else:
            await ctx.send(f'You\'re not currently participating in the reading challenge. Join us by using the `/join` command!')
    elif babble_active is not None:
        await ctx.send("You can't use that command. The reading challenge has not started yet.")
    else:
        await ctx.send('There is no active reading challenge.')


def parse_babble_params(params: str) -> Tuple[int, int]:
    """
    Used in babble command. Parses the parameters passed to the command.
    Returns a tuple of the form (start_in, duration).
    """
    parts = params.split()
    start_in = DEFAULT_START_IN
    duration = DEFAULT_DURATION

    for i in range(len(parts)):
        if parts[i] == "in":
            if i + 1 < len(parts): 
                try:
                    start_in = int(parts[i + 1])
                except ValueError:
                    pass
        elif parts[i] == "for":
            if i + 1 < len(parts):
                try:
                    duration = int(parts[i + 1])
                except ValueError:
                    pass
    return start_in, duration


async def send_babble_start_message(ctx, start_in, duration):
    """
    Used in babble command. Sends a message indicating the start of the reading challenge.
    Handles pluralization of the word "minute" for both start_in and duration.
    """
    start_plural = "s" if start_in > 1 else ""
    duration_plural = "s" if duration > 1 else ""
    join_msg = "\n   `/join` to jump in! \n   `/help` for a list of commands."

    await ctx.send(f'**The reading challenge will start in {start_in} minute{start_plural} and last for {duration} minute{duration_plural}.** {join_msg}')


async def send_babble_end_message(ctx):
    """
    Method used in babble command. Sends a message indicating the end of the reading challenge. Users have 3 minutes to submit their progress.
    If all participants do not submit their progress within 3 minutes, the scoreboard will be printed with all participants who submitted their progress.
    """
    global all_participants, progress_submitted, session_started, submit_end_time, start_sleep_task, session_sleep_task, babble_active

    if session_started is not None:
        await ctx.send("The reading challenge has ended!")
        await ctx.send("Participants, you have 3 minutes to submit your progress update using the `/progress` command.")
        
        submit_end_time = datetime.datetime.now() + datetime.timedelta(minutes=3)
        while datetime.datetime.now() < submit_end_time and not all(progress_submitted.values()):
            await asyncio.sleep(3)
        
        scoreboard = sorted(all_participants.items(), key=lambda x: x[1]['current'] - x[1]['initial'], reverse=True)
        
        if scoreboard:
            scoreboard_message = "Scoreboard:\n"
            for index, (participant, progress) in enumerate(scoreboard, start=1):
                difference = progress['current'] - progress['initial']
                scoreboard_message += f"{index}. {participant.mention} {difference} pages\n"
            winner = scoreboard[0][0]
            winner_difference = scoreboard[0][1]['current'] - scoreboard[0][1]['initial']
            scoreboard_message += f"The winner is: {winner.mention} with {winner_difference} pages!"
            await ctx.send(scoreboard_message)
        else:
            await ctx.send("No participants submitted their progress update.")
        babble_active, session_started, submit_end_time = None, None, None
        start_sleep_task, session_sleep_task = None, None
        all_participants.clear()
        progress_submitted.clear()
        return
    else:
        await ctx.send("There is no active reading challenge.")



async def send_babble_session_started_message(ctx):
    """
    Used in babble command. Sends a message indicating the start of the reading session.
    """
    channel = ctx.channel
    participants_list = [participant.mention for participant in all_participants.keys()]
    participant_mentions = " ".join(participants_list)
    await channel.send(f"{participant_mentions} The reading challenge has started! Enjoy reading!")


def get_page_number(participant):
    """
    Extracts the page number from a participant's progress.
    """
    progress = participant.progress
    if progress.startswith('pg:'):
        page = progress[3:].lstrip()
    elif progress.startswith('pg '):
        page = progress[2:].lstrip()
    else:
        page = progress
    if page.isdigit():
        return int(page)
    return 0


@bot.command()
async def help(ctx):
    commands = {
        "/babble [start] [duration]": "Starts a reading challenge. By default, it starts in 1 minute and lasts for 30 minutes.",
        "/join [initial_progress]": "Join the reading challenge. Optionally, specify your initial progress, e.g. /join pg: 1.",
        "/end": "Ends the current reading challenge.",
        "/drop": "Drops out of the current reading challenge.",
        "/timer": "Shows the time left until the start or end of the reading challenge.",
        "/participants": "Lists all the participants of the reading challenge.",
        "/progress [pages]": "Update your progress in the reading challenge, e.g. /progress pg: 5.",
        "/help": "Shows a list of available commands and their descriptions.",
    }

    help_text = ""
    for command, description in commands.items():
        help_text += f"`{command}`: {description}\n"

    await ctx.send(help_text)

bot.run(os.getenv('DISCORD_TOKEN'))
