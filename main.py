import os
import asyncio
import discord
import datetime
from discord.ext import commands
from dotenv import load_dotenv
from typing import Tuple

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='/', intents=intents, help_command=None)

participants = {}
progress_submitted = {}
babble_active = None
session_started = None
start_in = 0
duration = 30
start_time = None
end_time = None
session_sleep_task = None
start_sleep_task = None

DEFAULT_START_IN = 1
DEFAULT_DURATION = 30


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')


@bot.command()
async def babble(ctx, *, params: str = "1 30"):
    global babble_active, session_started, participants, progress_submitted, start_in, duration, start_time, end_time, start_sleep_task, session_sleep_task
    if not babble_active:
        try:
            babble_active = datetime.datetime.now()
            start_in, duration = parse_babble_params(params)
            start_time = datetime.datetime.now() + datetime.timedelta(minutes=start_in)
            end_time = start_time + datetime.timedelta(minutes=duration)

            await send_babble_start_message(ctx, start_in, duration)

            participants = {}
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
    else:
        await ctx.send('There is already an active reading challenge.')


@bot.command()
async def skip(ctx):
    global babble_active, start_sleep_task, session_sleep_task, session_started

    if babble_active is not None:
        if session_started is None:
            if start_sleep_task and not start_sleep_task.done():
                start_sleep_task.cancel()
                await ctx.send('The reading challenge will start immediately!')
                await start_session(ctx)
            else:
                await ctx.send('The reading challenge is already in progress. You cannot skip to the start again.')
        else:
            if session_sleep_task and not session_sleep_task.done():
                session_sleep_task.cancel()
                await send_babble_end_message(ctx)
            else:
                await ctx.send('The reading challenge has already ended. You cannot skip to the end again.')
    else:
        await ctx.send('There is no active reading challenge.')


async def start_session(ctx):
    global session_sleep_task, session_started
    session_started = datetime.datetime.now()
    await send_babble_session_started_message(ctx)
    session_sleep_task = asyncio.create_task(asyncio.sleep(duration * 60))
    await session_sleep_task
    await send_babble_end_message(ctx)
    session_started = None


@bot.command()
async def join(ctx, *initial_progress):
    """
    Allows a user to join the current reading session. The user can supply an optional parameter 
    to indicate their initial progress in the session. This function accepts an arbitrary number 
    of string arguments (represented by *initial_progress), packs them into a tuple, 
    and then combines them into a single string. This is done to handle the input of "pg: 1", 
    where a space is included after the colon. Without this, Python would treat "pg:" and "1" 
    as separate arguments, which would break the command.
    
    supports: /join __ where the blank is an optional parameter (using 1 for example):
        pg: 1
        pg 1
        pg1
        pg:1
    """
    global babble_active, participants, progress_submitted
    if babble_active is not None:
        if ctx.author not in participants:
            participants[ctx.author] = 0
            progress_submitted[ctx.author] = False
            initial_progress = " ".join(initial_progress)

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
                    participants[ctx.author] = page_number
                    await ctx.send(f'{ctx.author.mention} has joined the reading challenge! Starting at: page {page_number}')
                else:
                    del participants[ctx.author]
                    del progress_submitted[ctx.author]
                    await ctx.send(f'The initial progress provided is not a valid page number. Please try joining again. Use /help for more information.')
            else:
                await ctx.send(f'{ctx.author.mention} has joined the reading challenge!')
        else:
            await ctx.send(f'You\'re already participating in the reading challenge! If you\'d like to update your progress, use the /drop command and then rejoin the challenge.')
    else:
        await ctx.send('There is no active reading challenge.')


@bot.command()
async def end(ctx):
    """
    Function to end the current session. Will clear the participants list and set babble_active and session_started to None.
    """
    global babble_active, session_started, start_sleep_task, session_sleep_task, participants, progress_submitted
    if babble_active is not None:
        babble_active, session_started = None, None
        start_sleep_task.cancel()
        if session_sleep_task is not None:  # Check if the session_sleep_task exists before trying to cancel it
            session_sleep_task.cancel()  # Cancels the session sleep task
        
        participants.clear()
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
    global babble_active, participants, progress_submitted
    if babble_active is not None:
        if ctx.author in participants:
            del participants[ctx.author]
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
    global end_time, start_time, babble_active, session_started
    if babble_active is not None and session_started is None:
        time_left = start_time - datetime.datetime.now()
        minutes = time_left.seconds // 60
        seconds = time_left.seconds % 60
        print(time_left)
        await ctx.send(f"The session will start in {minutes} minutes and {seconds} seconds.")
    elif babble_active is not None and session_started is not None:
        time_left = end_time - datetime.datetime.now()
        minutes = time_left.seconds // 60
        seconds = time_left.seconds % 60
        await ctx.send(f"The session will end in {minutes} minutes and {seconds} seconds. Good luck!")
    else:
        await ctx.send("There is no active reading challenge.")


@bot.command()
async def participants(ctx):
    """
    Lists all the participants in the reading challenge.
    """
    global participants
    if participants:
        participants_list = "\n".join(member.display_name for member in participants.keys())
        await ctx.send(f"Participants:\n{participants_list}")
    else:
        await ctx.send("There are no participants in the reading challenge.")


@bot.command()
async def progress(ctx, *, progress: str):
    """
    Allows a user to update their progress after the session has ended.
    The progress should be provided in the format "pg: X" or "pg X", where X is the page number.
    """
    global participants, progress_submitted, session_started
    if session_started is not None:
        if ctx.author in participants:
            if progress:
                if progress.startswith('pg:'):
                    page = progress[3:].lstrip()
                elif progress.startswith('pg '):
                    page = progress[2:].lstrip()
                else:
                    page = progress

                if page.isdigit():
                    page_number = int(page)
                    participants[ctx.author] = page_number
                    progress_submitted[ctx.author] = True
                    await ctx.send(f'{ctx.author.mention} has updated their progress to: page {page_number}')
                else:
                    await ctx.send(f'The progress provided is not a valid page number. Please try updating again.')
            else:
                await ctx.send('Please provide your progress in the format `/progress pg X` or `/progress X`, where X is the page number.')
        else:
            await ctx.send(f'You\'re not currently participating in the reading challenge. Join us by using the `/join` command!')
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
    Used in babble command. Sends a message indicating the end of the reading challenge
    and displays the scoreboard of participants' progress.
    """
    global participants, progress_submitted, session_started

    if session_started is not None:
        session_end = session_started + datetime.timedelta(minutes=5)
        time_left = session_end - datetime.datetime.now()
        minutes = time_left.seconds // 60
        seconds = time_left.seconds % 60

        if participants:
            await ctx.send("The reading challenge has ended!")
            await asyncio.sleep(1)
            await ctx.send("Participants, you have 5 minutes to submit your progress update using the `/progress` command.")
            await asyncio.sleep(5 * 60)  # Wait for 5 minutes to allow participants to submit their updates

            while not all(progress_submitted.values()):
                await asyncio.sleep(1)  # Check every second if all participants have submitted their progress

            scoreboard = sorted(participants.items(), key=lambda x: x[1], reverse=True)

            if scoreboard:
                scoreboard_message = "Scoreboard:\n"
                for index, (participant, page_number) in enumerate(scoreboard, start=1):
                    scoreboard_message += f"{index}. {participant.mention}: page {page_number}\n"
                winner = scoreboard[0][0]
                scoreboard_message += f"The winner is: {winner.mention} with page {scoreboard[0][1]}!"
                await ctx.send(scoreboard_message)
            else:
                await ctx.send("No participants submitted their progress update.")
            return

        else:
            await ctx.send("The reading challenge has ended. No participants joined the challenge.")
    else:
        await ctx.send("There is no active reading challenge.")


async def send_babble_session_started_message(ctx):
    """
    Used in babble command. Sends a message indicating the start of the reading session.
    """
    channel = ctx.channel
    participants_list = [participant.mention for participant in participants.keys()]
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


bot.run(os.getenv('DISCORD_TOKEN'))

# TODO: fix code , when /skip is called the duration/end time should update to current time + duration 
# TODO: scoreboard not updating when user submits progress (when all users submit progress)
# TODO: timer sometimes showing crazy high number ; incorporate a stop time for the timer