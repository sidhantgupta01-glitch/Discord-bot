import discord
import json
import os
import random
import time
import logging
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()  # reads .env if it exists (local testing only)

# ---------- SETTINGS ----------
TOKEN = os.getenv("TOKEN")  # set in .env locally, or in the host's settings
GAME_LINK = "https://www.roblox.com/games/YOUR_GAME_ID"
WELCOME_CHANNEL = "bot-test"   # name of your welcome channel
AUTO_ROLE = "Member"          # role given after verifying
STAFF_ROLE = "Staff"          # role that can see tickets
TICKET_CATEGORY = "🎫 SUPPORT"   # category tickets go in

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)


# ---------- STARTUP ----------
synced = False

@bot.event
async def on_ready():
    print("Bot is online as", bot.user)
    global synced
    if not synced:
        synced = True
        # register / commands straight to each server (shows instantly)
        for guild in bot.guilds:
            bot.tree.copy_global_to(guild=guild)
            cmds = await bot.tree.sync(guild=guild)
            print("Synced", len(cmds), "slash commands to", guild.name)
        # remove old global copies so commands don't show twice
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()


# ---------- WELCOME ----------
@bot.event
async def on_member_join(member):
    channel = discord.utils.get(member.guild.text_channels, name=WELCOME_CHANNEL)
    if channel:
        await channel.send("Welcome " + member.mention + "! Verify in #verify, then play here: " + GAME_LINK)


# ---------- FUN / INFO ----------
@bot.hybrid_command()
async def hello(ctx):
    await ctx.send("Hello " + ctx.author.mention + "!")


@bot.hybrid_command()
async def game(ctx):
    await ctx.send("Play the game: " + GAME_LINK)


# ---------- MODERATION ----------
@bot.hybrid_command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason"):
    await member.kick(reason=reason)
    await ctx.send(member.name + " was kicked. Reason: " + reason)


@bot.hybrid_command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason"):
    await member.ban(reason=reason)
    await ctx.send(member.name + " was banned. Reason: " + reason)


@bot.hybrid_command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    if ctx.interaction:  # used as /clear
        await ctx.defer(ephemeral=True)
        await ctx.channel.purge(limit=amount)
        await ctx.send("Deleted " + str(amount) + " messages.", ephemeral=True)
    else:  # used as !clear
        await ctx.channel.purge(limit=amount + 1)
        await ctx.send("Deleted " + str(amount) + " messages.", delete_after=3)


# ---------- VERIFICATION ----------
class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.blurple, custom_id="verify")
    async def verify(self, interaction, button):
        role = discord.utils.get(interaction.guild.roles, name=AUTO_ROLE)
        if role is None:
            await interaction.response.send_message("Member role not found. Tell an admin.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message("You're already verified.", ephemeral=True)
            return
        await interaction.user.add_roles(role)
        await interaction.response.send_message("Verified! Welcome to the server.", ephemeral=True)


@bot.hybrid_command()
@commands.has_permissions(administrator=True)
async def verifypanel(ctx):
    embed = discord.Embed(title="Verification", description="Click the button below to get access to the server.", color=discord.Color.blurple())
    await ctx.send(embed=embed, view=VerifyView())


# ---------- TICKETS ----------
class CloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red, custom_id="close_ticket")
    async def close(self, interaction, button):
        await interaction.response.send_message("Closing ticket...")
        await interaction.channel.delete()


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.green, custom_id="open_ticket")
    async def open_ticket(self, interaction, button):
        guild = interaction.guild
        user = interaction.user
        name = "ticket-" + str(user.id)

        # stop people opening more than one ticket
        if discord.utils.get(guild.text_channels, name=name):
            await interaction.response.send_message("You already have a ticket open.", ephemeral=True)
            return

        category = discord.utils.get(guild.categories, name=TICKET_CATEGORY)
        if category is None:
            category = await guild.create_category(TICKET_CATEGORY)

        # only the user, staff, and the bot can see the channel
        perms = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True),
        }
        staff = discord.utils.get(guild.roles, name=STAFF_ROLE)
        if staff:
            perms[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        channel = await guild.create_text_channel(name, category=category, overwrites=perms)
        await channel.send(user.mention + " explain your problem. Staff will help soon.", view=CloseView())
        await interaction.response.send_message("Ticket created: " + channel.mention, ephemeral=True)


@bot.hybrid_command()
@commands.has_permissions(administrator=True)
async def ticketpanel(ctx):
    embed = discord.Embed(title="Support", description="Need help? Click the button below.", color=discord.Color.green())
    await ctx.send(embed=embed, view=TicketView())


# ---------- LEVELS / XP ----------
XP_FILE = "levels.json"
XP_COOLDOWN = 60  # seconds between XP gains per user (stops spam farming)
last_xp = {}

if os.path.exists(XP_FILE):
    with open(XP_FILE) as f:
        levels = json.load(f)
else:
    levels = {}


def save_levels():
    with open(XP_FILE, "w") as f:
        json.dump(levels, f)


def xp_needed(level):
    return (level + 1) * 100  # level 0->1 = 100 XP, 1->2 = 200 XP, ...


@bot.event
async def on_message(message):
    if message.author.bot or message.guild is None:
        return

    uid = str(message.author.id)
    now = time.time()
    if now - last_xp.get(uid, 0) >= XP_COOLDOWN:
        last_xp[uid] = now
        data = levels.setdefault(uid, {"xp": 0, "level": 0})
        data["xp"] += random.randint(15, 25)
        if data["xp"] >= xp_needed(data["level"]):
            data["xp"] -= xp_needed(data["level"])
            data["level"] += 1
            await message.channel.send("🎉 " + message.author.mention + " reached level " + str(data["level"]) + "!")
        save_levels()

    await bot.process_commands(message)  # keeps ! commands working


@bot.hybrid_command()
async def rank(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = levels.get(str(member.id), {"xp": 0, "level": 0})
    await ctx.send(member.name + " — Level " + str(data["level"]) + " (" + str(data["xp"]) + "/" + str(xp_needed(data["level"])) + " XP)")


@bot.hybrid_command()
async def leaderboard(ctx):
    top = sorted(levels.items(), key=lambda x: (x[1]["level"], x[1]["xp"]), reverse=True)[:10]
    lines = []
    for i, (uid, data) in enumerate(top, start=1):
        member = ctx.guild.get_member(int(uid))
        name = member.name if member else "Unknown"
        lines.append(str(i) + ". " + name + " — Level " + str(data["level"]))
    embed = discord.Embed(title="🏆 Leaderboard", description="\n".join(lines) or "No one has XP yet.", color=discord.Color.gold())
    await ctx.send(embed=embed)


# ---------- KEEP BUTTONS WORKING AFTER RESTART ----------
async def setup_hook():
    bot.add_view(VerifyView())
    bot.add_view(TicketView())
    bot.add_view(CloseView())

bot.setup_hook = setup_hook


# ---------- ERRORS ----------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission for that.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Missing something. Example: !kick @user reason")
    elif isinstance(error, commands.CommandNotFound):
        pass  # ignore typos like !helo
    else:
        print("Command error in", ctx.command, ":", repr(error))
        try:
            await ctx.send("Something went wrong running that command.")
        except discord.HTTPException:
            pass


@bot.event
async def on_error(event, *args, **kwargs):
    logging.exception("Error in event " + event)  # print it, keep running


# ---------- START ----------
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("ERROR: TOKEN is not set. Put TOKEN=... in .env (local) or in the host's environment variables.")
    bot.run(TOKEN)  # bot.run also sets up logging so errors show in the console
