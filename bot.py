import csv
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import discord
import pytz
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

## PLEASE EDIT THESE WITH THE CORRECT VALUES
ACTIVITY = os.getenv("ACTIVITY_STATUS")
TOKEN = os.getenv("TOKEN")
DATABASE = "timezones.db"
MOVIES_CSV = "movies.csv"
## STOP EDITING

with sqlite3.connect(DATABASE) as db:
    cur = db.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS users_data(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE, offset INTEGER);"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS alert_times(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE, start TEXT, end TEXT);"
    )
    db.commit()
    cur.close()


# DISCORD BOT
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

activity = discord.Activity(name=ACTIVITY, type=discord.ActivityType.watching)
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    description="Alerts users when a IMDB/Letterboxd link gets posted between their timeframes",
    activity=activity,
)


def in_between(now, start, end):
    if start <= end:
        return start <= now <= end
    else:
        return start <= now or now <= end


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if (
        "imdb.com/title/" in message.content.lower()
        or "letterboxd.com/film/" in message.content.lower()
    ):
        movie_links = re.findall(r"(https?://[^\s]+)", message.content)
        imdb_urls = [url for url in movie_links if "imdb" in url]
        with sqlite3.connect(DATABASE) as db:
            cur = db.cursor()
            offset = cur.execute(
                f"SELECT offset FROM users_data WHERE user_id={message.author.id};"
            ).fetchone()
            if offset:
                offset = int(offset[0])
            else:
                offset = 0
        if len(imdb_urls) > 0:
            for imdb_url in imdb_urls:
                watched_date = str(
                    (message.created_at + timedelta(hours=offset)).date()
                )
                imdb_id = str(imdb_url.split("/")[4])
                with open(MOVIES_CSV, "a", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    row = [watched_date, imdb_id]
                    writer.writerow(row)
        with sqlite3.connect(DATABASE) as db:
            cur = db.cursor()
            all_users_offsets = cur.execute(
                "SELECT user_id,offset FROM users_data;"
            ).fetchall()
            for user in all_users_offsets:
                user_alert_times = cur.execute(
                    f"SELECT start,end FROM alert_times WHERE user_id={user[0]};"
                ).fetchone()
                if user_alert_times is None:
                    continue
                start_hour = int(user_alert_times[0].split(":")[0])
                start_minute = int(user_alert_times[0].split(":")[1])
                user_tz = timezone(timedelta(hours=user[1]))
                start_dt = datetime(
                    datetime.now().year,
                    datetime.now().month,
                    datetime.now().day,
                    start_hour,
                    start_minute,
                    0,
                ).time()
                end_hour = int(user_alert_times[1].split(":")[0])
                end_minute = int(user_alert_times[1].split(":")[1])
                end_dt = datetime(
                    datetime.now().year,
                    datetime.now().month,
                    datetime.now().day,
                    end_hour,
                    end_minute,
                    0,
                ).time()
                now = datetime.now().astimezone(user_tz).time()
                if in_between(now, start_dt, end_dt):
                    for member in bot.get_all_members():
                        if member.id == user[0]:
                            await member.send(
                                f"{message.author.mention} has started a stream on {message.guild.name}!\n{' | '.join(movie_links)}"
                            )
    await bot.process_commands(message)


@bot.event
async def on_ready():
    if not os.path.isfile(MOVIES_CSV):
        with open(MOVIES_CSV, "w", encoding="utf-8", newline="") as f:
            header = ["WatchedDate", "imdbID"]
            writer = csv.writer(f)
            writer.writerow(header)
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")


@bot.tree.command(name="signup", description="Initial registration for alerts")
async def user_signup(interaction: discord.Interaction):
    with sqlite3.connect(DATABASE) as db:
        cur = db.cursor()
        exists = cur.execute(
            f"SELECT * FROM users_data WHERE user_id={interaction.user.id};"
        ).fetchone()
        if exists is not None:
            return await interaction.response.send_message(
                "You are already signed up!  Change your settings with `/set_alert_hours` or `/set_offset`.",
                ephemeral=True,
                delete_after=60,
            )
        else:
            cur.execute(
                f"INSERT INTO users_data(user_id,offset) VALUES({interaction.user.id}, 0);"
            )
            cur.execute(
                f"INSERT INTO alert_times(user_id,start,end) VALUES({interaction.user.id}, '00:00', '23:59');"
            )
            db.commit()
            cur.close()
            return await interaction.response.send_message(
                "You have been signed up for alerts!\n**Default settings are:\n`offset`:  UTC\n`alert hours`:  00:00-23:59**\nChange your settings with `/set_alert_hours` or `/set_offset`.",
                ephemeral=True,
                delete_after=120,
            )


@bot.tree.command(name="get_csv", description=f"Attaches the current {MOVIES_CSV} file")
async def get_csv(interaction: discord.Interaction):
    if os.path.isfile(MOVIES_CSV):
        csv_file = discord.File(
            os.path.abspath(MOVIES_CSV),
            filename=MOVIES_CSV,
            description=f"Current {MOVIES_CSV} file",
        )
        await interaction.response.send_message(
            content="Current CSV file!", file=csv_file, ephemeral=True, delete_after=60
        )
    else:
        await interaction.response.send_message(
            f"No {MOVIES_CSV} file has been created yet. Creating one now!",
            ephemeral=True,
            delete_after=60,
        )
        with open(MOVIES_CSV, "w", encoding="utf-8", newline="") as f:
            header = ["WatchedDate", "imdbID"]
            writer = csv.writer(f)
            writer.writerow(header)


@bot.tree.command(
    name="set_alert_hours", description="Sets the start and end time you want alerts"
)
@app_commands.describe(
    start="Time in 'HH:MM' 24-hour format including a leading 0 (uses your local time)"
)
@app_commands.describe(
    end="Time in 'HH:MM' 24-hour format including a leading 0 (uses your local time)"
)
async def set_user_alert_hours(interaction: discord.Interaction, start: str, end: str):
    with sqlite3.connect(DATABASE) as db:
        cur = db.cursor()
        exists = cur.execute(
            f"SELECT * FROM alert_times WHERE user_id={interaction.user.id};"
        ).fetchone()
    if not exists:
        return await interaction.response.send_message(
            "Please first sign up using `/signup`, then change your settings with this command.",
            ephemeral=True,
            delete_after=60,
        )
    format = re.compile("^(?:[01]?\d|2[0-3])(?::[0-5]\d){1,2}$")
    if not format.match(start) or not format.match(end):
        return await interaction.response.send_message(
            "Start and End must be in the format `HH:MM` using 24-hour time, including a leading 0 (eg. 09:00).",
            ephemeral=True,
            delete_after=60,
        )
    with sqlite3.connect(DATABASE) as db:
        cur = db.cursor()
        cur.execute(
            f"UPDATE alert_times SET start='{start}', end='{end}' WHERE user_id={interaction.user.id};"
        )
        db.commit()
        cur.close()
        await interaction.response.send_message(
            f"Set start to: `{start}`\nSet end to: `{end}`",
            ephemeral=True,
            delete_after=60,
        )


@bot.tree.command(name="set_offset", description="Sets your local timezone")
@app_commands.describe(
    timezone="The name of your timezone (eg. US/Eastern ) if you leave it blank, uses UTC"
)
async def set_user_offset(interaction: discord.Interaction, timezone: str = "UTC"):
    with sqlite3.connect(DATABASE) as db:
        cur = db.cursor()
        exists = cur.execute(
            f"SELECT * FROM users_data WHERE user_id={interaction.user.id};"
        ).fetchone()
    if not exists:
        return await interaction.response.send_message(
            "Please first sign up using `/signup`, then change your settings with this command.",
            ephemeral=True,
            delete_after=60,
        )
    try:
        user_offset = (
            datetime.now(pytz.timezone(timezone)).utcoffset().total_seconds() / 60 / 60
        )
        with sqlite3.connect(DATABASE) as db:
            cur = db.cursor()
            cur.execute(
                f"UPDATE users_data SET offset={user_offset} WHERE user_id={interaction.user.id};"
            )
            db.commit()
            cur.close()
        await interaction.response.send_message(
            f"Your offset is now: `{user_offset}` using the timezone: `{timezone}`.\nCurrent time there is `{datetime.now(tz=pytz.timezone(timezone)).strftime('%H:%M')}`.",
            ephemeral=True,
            delete_after=120,
        )
    except Exception as e:
        await interaction.response.send_message(
            f"Please input a valid timezone from either of these sources:\nhttps://en.wikipedia.org/wiki/List_of_tz_database_time_zones\nhttps://en.wikipedia.org/wiki/List_of_time_zone_abbreviations",
            ephemeral=True,
            delete_after=60,
        )


bot.run(TOKEN)
