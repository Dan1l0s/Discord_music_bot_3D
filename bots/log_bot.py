import disnake
from disnake.ext import commands
import asyncio
import sys
from typing import Dict

import configs.private_config as private_config
import configs.public_config as public_config

import helpers.helpers as helpers
import helpers.database_logger as database_logger

from helpers.embedder import Embed
from helpers.helpers import GuildOption


class Activity():
    acttype = None
    actname = None

    def __init__(self, acttype=None, actname=None):
        self.acttype = acttype
        self.actname = actname

    def __eq__(self, other):
        return self.acttype == other.acttype and self.actname == other.actname


class UserStatus():
    status = None
    activities = None
    updated = None

    def __init__(self, status):
        self.status = status
        self.activities = []
        self.updated = False

    def __eq__(self, other):
        a = set((x.acttype, x.actname) for x in self.activities)
        b = set((x.acttype, x.actname) for x in other.activities)
        return self.status == other.status and a == b


class LogBot():
    token = None
    name = None
    bot = None
    embedder = None

    def __init__(self, name: str, token: str):
        self.bot = commands.InteractionBot(intents=disnake.Intents.all(
        ), activity=disnake.Activity(name="everyone o_o", type=disnake.ActivityType.watching))
        self.name = name
        self.embedder = Embed()
        self.token = token

    # --------------------- MESSAGES --------------------------------

        @self.bot.event
        async def on_message(message):
            if not message.guild:
                if helpers.is_supreme_being(message.author):
                    await message.reply(public_config.on_message_supreme_being)
                return
            await self.check_mentions(message)

        @self.bot.event
        async def on_message_edit(before, after):
            if not before.author.guild:
                return
            if before.author.id in private_config.bot_ids.values():
                return
            guild_id = before.author.guild.id
            channel_id = await helpers.get_guild_option(guild_id, GuildOption.LOG_CHANNEL)
            if not channel_id:
                return
            channel = self.bot.get_channel(int(channel_id))
            if before.content != after.content:
                await channel.send(embed=self.embedder.message_edit(before, after))
            if before.pinned != after.pinned:
                if before.pinned:
                    await channel.send(embed=self.embedder.message_unpin(before, after))
                else:
                    await channel.send(embed=self.embedder.message_pin(before, after))

        @self.bot.event
        async def on_message_delete(message):
            if not message.author.guild:
                return
            channel_id = await helpers.get_guild_option(message.author.guild.id, GuildOption.LOG_CHANNEL)
            if not channel_id:
                return
            channel = self.bot.get_channel(int(channel_id))
            if message.author.id not in private_config.bot_ids.values():
                await channel.send(embed=self.embedder.message_delete(message))

    # --------------------- ACTIONS --------------------------------
        @self.bot.event
        async def on_audit_log_entry_create(entry):
            channel_id = await helpers.get_guild_option(entry.user.guild.id, GuildOption.LOG_CHANNEL)
            if not channel_id:
                return
            channel = self.bot.get_channel(int(channel_id))
            s = f"entry_{str(entry.action)[15:]}"
            if hasattr(database_logger, s):
                log = getattr(database_logger, s)
                await log(entry)
            if hasattr(self.embedder, s):
                s = getattr(self.embedder, s)
                await channel.send(embed=s(entry))

        @self.bot.event
        async def on_member_update(before, after):
            channel_id = await helpers.get_guild_option(before.guild.id, GuildOption.LOG_CHANNEL)
            if not channel_id:
                return
            channel = self.bot.get_channel(int(channel_id))
            # await database_logger.member_update(after)
            await channel.send(embed=self.embedder.profile_upd(before, after))

        @self.bot.event
        async def on_raw_member_remove(payload):
            channel_id = await helpers.get_guild_option(payload.guild_id, GuildOption.LOG_CHANNEL)
            if not channel_id:
                return
            channel = self.bot.get_channel(int(channel_id))
            await database_logger.member_remove(payload)
            await channel.send(embed=self.embedder.member_remove(payload))

        @self.bot.event
        async def on_member_join(member):
            welcome_channel_id = await helpers.get_guild_option(member.guild.id, GuildOption.WELCOME_CHANNEL)
            log_channel_id = await helpers.get_guild_option(member.guild.id, GuildOption.LOG_CHANNEL)

            if welcome_channel_id:
                welcome_channel = self.bot.get_channel(int(welcome_channel_id))
                user = self.bot.get_user(member.id)
                await welcome_channel.send(embed=self.embedder.welcome_message(member, user))
                message = await welcome_channel.send(f"{member.mention}")
                await message.delete()

            if log_channel_id:
                log_channel = self.bot.get_channel(int(log_channel_id))
                await database_logger.member_join(member)
                await log_channel.send(embed=self.embedder.member_join(member))

        @ self.bot.event
        async def on_member_ban(guild, user):
            channel_id = await helpers.get_guild_option(guild.id, GuildOption.LOG_CHANNEL)
            if not channel_id:
                return
            channel = self.bot.get_channel(int(channel_id))
            await channel.send(embed=self.embedder.ban(guild, user))

        @ self.bot.event
        async def on_member_unban(guild, user):
            channel_id = await helpers.get_guild_option(guild.id, GuildOption.LOG_CHANNEL)
            if not channel_id:
                return
            channel = self.bot.get_channel(int(channel_id))
            await channel.send(embed=self.embedder.unban(guild, user))

    # --------------------- VOICE STATES --------------------------------
        @ self.bot.event
        async def on_voice_state_update(member, before: disnake.VoiceState, after: disnake.VoiceState):
            channel_id = await helpers.get_guild_option(member.guild.id, GuildOption.LOG_CHANNEL)
            if not channel_id:
                return
            channel = self.bot.get_channel(int(channel_id))

            if before.channel and after.channel:
                if before.channel.id != after.channel.id:
                    await database_logger.switched(member, before, after)
                    if not after.afk:  # REGULAR SWITCH
                        await channel.send(embed=self.embedder.switched(member, before, after))
                    else:  # AFK
                        await channel.send(embed=self.embedder.afk(member, after))
                else:
                    for attr in dir(after):
                        if attr in public_config.on_v_s_update:
                            if getattr(after, attr) != getattr(before, attr) and hasattr(self.embedder, attr):
                                log = getattr(database_logger, attr)
                                await log(member, after)
                                s = getattr(self.embedder, attr)
                                await channel.send(embed=s(member, after))
            elif before.channel:
                await database_logger.disconnected(member, before)
                await channel.send(embed=self.embedder.disconnected(member, before))
            else:
                await database_logger.connected(member, after)
                await channel.send(embed=self.embedder.connected(member, after))

    # --------------------- RANDOM --------------------------------
        @ self.bot.event
        async def on_ready():
            await database_logger.enabled(self.bot)
            print(f"{self.name} is logged as {self.bot.user}")
            await self.status_check()

        @ self.bot.event
        async def on_disconnect():
            print(f"{self.name} has disconnected from Discord")
            # await database_logger.lost_connection(self.bot)

        @self.bot.event
        async def on_connect():
            print(f"{self.name} has connected to Discord")
            # await self.status_check()

    # --------------------- SLASH COMMANDS --------------------------------

        @self.bot.slash_command(description="Creates a welcome banner for a new member (manually)")
        async def welcome(inter: disnake.AppCmdInter, member: disnake.Member):
            await inter.response.defer()

            if await self.check_dm(inter):
                return

            user = self.bot.get_user(member.id)
            embed = self.embedder.welcome_message(member, user)
            await helpers.try_function(inter.delete_original_response, True)
            await inter.channel.send(embed=embed)
            message = await inter.channel.send(f"{member.mention}")
            await helpers.try_function(message.delete, True)

        @ self.bot.slash_command(description="Check current status of user")
        async def status(inter: disnake.AppCmdInter, member: disnake.User):
            await inter.response.defer()

            if await self.check_dm(inter):
                return
            await inter.edit_original_response(embed=self.embedder.get_status(member))

        @ self.bot.slash_command()
        async def set(inter: disnake.AppCmdInter):
            pass

        @ set.sub_command_group()
        async def logs(inter: disnake.AppCmdInter):
            pass

        @ logs.sub_command(description="Allows admin to set channel for common logs")
        async def common(inter: disnake.AppCmdInter, channel: disnake.TextChannel = commands.Param(description='Select text channel for common logs')):
            await inter.response.defer()

            if await self.check_dm(inter):
                return

            if not await helpers.is_admin(inter.author):
                return await inter.edit_original_response("Unauthorized access, you are not the Supreme Being!")

            await helpers.set_guild_option(inter.guild.id, GuildOption.LOG_CHANNEL, channel.id)
            await inter.edit_original_response(f'New log channel is {channel.mention}')

        @ logs.sub_command(description="Allows admin to set channel for status logs")
        async def status(inter: disnake.AppCmdInter, channel: disnake.TextChannel = commands.Param(description='Select text channel for status logs')):
            await inter.response.defer()

            if await self.check_dm(inter):
                return

            if not await helpers.is_admin(inter.author):
                return await inter.edit_original_response("Unauthorized access, you are not the Supreme Being!")
            await helpers.set_guild_option(inter.guild.id, GuildOption.STATUS_LOG_CHANNEL, channel.id)
            await inter.edit_original_response(f'New status log channel is {channel.mention}')

        @ logs.sub_command(description="Allows admin to set channel for welcome logs")
        async def welcome(inter: disnake.AppCmdInter, channel: disnake.TextChannel = commands.Param(description='Select text channel for welcomes logs')):
            await inter.response.defer()

            if await self.check_dm(inter):
                return

            if not await helpers.is_admin(inter.author):
                return await inter.edit_original_response("Unauthorized access, you are not the Supreme Being!")

            await helpers.set_guild_option(inter.guild.id, GuildOption.WELCOME_CHANNEL, channel.id)
            await inter.edit_original_response(f'New welcome channel is {channel.mention}')

    # --------------------- METHODS --------------------------------

    async def run(self):
        await self.bot.start(self.token)

    async def check_dm(self, inter):
        if not inter.guild:
            await inter.edit_original_response((public_config.dm_error, public_config.dm_error_supreme_being)[helpers.is_supreme_being(inter.author)])
            return True
        return False

    async def status_check(self):
        prev_status = {}
        while not self.bot.is_closed():
            try:
                delayed_tasks = []
                new_status = {}
                status_channels = {}
                guild_list = self.bot.guilds
                for guild in guild_list:
                    status_log_channel_id = await helpers.get_guild_option(guild.id, GuildOption.STATUS_LOG_CHANNEL)
                    if status_log_channel_id:
                        status_channels[guild.id] = status_log_channel_id
                        for member in guild.members:
                            if member.bot:
                                continue
                            new_status[member] = UserStatus(None)
                self.gen_status_and_activity(new_status)

                for member, status in new_status.items():
                    if not member in prev_status or status == prev_status[member]:
                        continue
                    status.updated = True
                    if status.status != prev_status[member].status:
                        delayed_tasks.append(database_logger.status_upd(member))
                    if status.activities != prev_status[member].activities:
                        delayed_tasks.append(database_logger.activity_upd(member, prev_status[member], status))
                for guild in guild_list:
                    if not guild.id in status_channels.keys():
                        continue
                    for member in guild.members:
                        if not member.bot and new_status[member].updated:
                            channel = self.bot.get_channel(status_channels[guild.id])
                            delayed_tasks.append(channel.send(embed=self.embedder.activity_update(member, prev_status[member], new_status[member])))
                asyncio.create_task(helpers.run_delayed_tasks(delayed_tasks))
                prev_status = new_status
                await asyncio.sleep(0.5)
            except Exception as ex:
                print(f"Exception in status log: {ex}", file=sys.stderr)
                pass

    def gen_status_and_activity(self, status_dict: Dict[disnake.Member, UserStatus]):
        for member, status in status_dict.items():
            status.status = str(member.status)
            for activity in member.activities:
                if isinstance(activity, type(disnake.activity.Spotify)):
                    status.activities.append(Activity(type(activity), f'{activity.artists[0]} - "{activity.title}"'))
                elif activity is not None:
                    status.activities.append(Activity(type(activity), f'{activity.name}'))

    async def check_mentions(self, message) -> bool:
        if len(message.role_mentions) > 0 or len(message.mentions) > 0:
            client = message.guild.me
            if helpers.is_mentioned(client, message):
                if await helpers.is_admin(message.author):
                    if "ping" in message.content.lower() or "пинг" in message.content.lower():
                        return await message.reply(f"Yes, my master. My ping is {round(self.bot.latency*1000)} ms")
                    else:
                        return await message.reply("At your service, my master.")
                else:
                    await helpers.try_function(message.author.timeout, True, duration=10, reason="Ping by inferior life form")
                    return await message.reply(f"How dare you tag me? Know your place, trash")
