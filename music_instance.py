import disnake
from disnake.ext import commands
from youtube_search import YoutubeSearch
from yt_dlp import YoutubeDL
from threading import Thread
import random
import asyncio

import config
import helpers
from embedder import Embed
from selection import SelectionPanel


class Interaction():
    orig_inter = None
    author = None
    guild = None
    text_channel = None
    voice_channel = None

    def __init__(self, bot, inter):
        self.guild = bot.get_guild(inter.guild.id)
        self.author = self.guild.get_member(inter.author.id)
        self.text_channel = bot.get_partial_messageable(inter.channel.id)
        self.orig_inter = inter
        if self.author.voice:
            self.voice_channel = self.author.voice.channel


class Song():
    track_info = None
    author = None
    original_message = None

    def __init__(self, author="Unknown author"):
        self.track_info = asyncio.Future()
        self.author = author


class GuildState():
    guild = None
    skip_flag = None
    repeat_flag = None
    paused = None
    last_inter = None
    voice = None
    cancel_timeout = None
    song_queue = None

    def __init__(self, guild):
        self.guild = guild
        self.skip_flag = False
        self.repeat_flag = False
        self.paused = False
        self.song_queue = []

    def reset(self):
        self.skip_flag = False
        self.repeat_flag = False
        self.paused = False
        self.song_queue.clear()

    async def connected_to(self, vc):
        while True:
            if self.voice.is_connected() and self.voice.channel == vc:
                print("Finnaly connected")
                break
            await asyncio.sleep(0.25)


class MusicBotInstance:
    bot = None
    name = None
    logger = None
    embedder = None
    states = None

# *_______ToInherit___________________________________________________________________________________________________________________________________________

    def __init__(self, name, logger):
        self.bot = commands.Bot(command_prefix="?", intents=disnake.Intents.all(
        ), activity=disnake.Activity(name="/play", type=disnake.ActivityType.listening))
        self.name = name
        self.logger = logger
        self.embedder = Embed()
        self.states = {}

        @self.bot.event
        async def on_ready():
            print(
                f"{self.name} is logged as {self.bot.user} (ID: {self.bot.application_id})")
            self.logger.enabled(self.bot)
            for guild in self.bot.guilds:
                self.states[guild.id] = GuildState(guild)
            # asyncio.create_task(self.print_voice())

        @self.bot.event
        async def on_guild_join(guild):
            self.states[guild.id] = GuildState(guild)

        @self.bot.event
        async def on_voice_state_update(member, before: disnake.VoiceState, after: disnake.VoiceState):
            guild_id = member.guild.id
            state = self.states[guild_id]
            if not state.voice or before.channel == after.channel:
                return
            if before.channel != state.voice.channel and after.channel != state.voice.channel:
                return
            if member.id == self.bot.application_id and not after.channel:
                return await self.abort_play(guild_id, message="Disconnected")
            if len(state.voice.channel.members) < 2:
                print(f"Timeout begin: {self.name}")
                await self.timeout(guild_id)
            else:
                await self.cancel_timeout(guild_id)

    async def run(self):
        await self.bot.start(config.tokens[self.name])

    # async def print_voice(self):
    #     while True:
    #         await asyncio.sleep(0.25)
    #         state = self.states[569924343010689025]
    #         if not state.voice:
    #             print("None")
    #         else:
    #             print(
    #                 f"Voice: {state.voice}, {bool (state.voice.is_connected())}, {bool (state.voice.is_playing())},  {bool (state.voice.is_paused())} ")

# *_______ForLeader________________________________________________________________________________________________________________________________________

    def contains_in_guild(self, guild_id):
        return guild_id in self.states

    def available(self, guild_id):
        print(f"{self.name}: {self.states[guild_id].voice}")
        return bool(self.states[guild_id].voice == None)

    def timeout(self, guild_id):
        if not self.states[guild_id].voice:
            return False
        return bool(self.states[guild_id].cancel_timeout != None)

    def current_voice_channel(self, guild_id):
        if not self.states[guild_id].voice:
            return None
        return self.states[guild_id].voice.channel

# *_______Helpers________________________________________________________________________________________________________________________________________

    async def timeout(self, guild_id):
        state = self.states[guild_id]
        tm = config.music_settings["PlayTimeout"]
        message = await state.last_inter.text_channel.send(f"I am left alone, I will leave VC in {tm} seconds!")
        if state.voice.is_playing():
            state.voice.pause()
        state.cancel_timeout = asyncio.Future()
        try:
            resume = await asyncio.wait_for(state.cancel_timeout, tm)
            print("Timeout was canceled")
            await message.delete()
            if resume and not state.paused:
                print("Resuming play")
                state.voice.resume()
        except:
            print("Timeout was not canceled")
            await self.abort_play(guild_id, message="Timeout")
        state.cancel_timeout = None

    async def cancel_timeout(self, guild_id, resume=True):
        state = self.states[guild_id]
        if state.cancel_timeout and not state.cancel_timeout.done():
            print(f"Timeout end: {self.name}")
            state.cancel_timeout.set_result(resume)

    async def abort_play(self, guild_id, message="Finished playing music!"):
        print(f"Aborting task with message: {message}")
        state = self.states[guild_id]
        if state.voice:
            try:
                voice = state.voice
                state.voice = None
                voice.stop()
                await voice.disconnect()
                await state.last_inter.text_channel.send(message)
            except:
                pass
        state.reset()

    async def process_song_query(self, inter, query, song=None):
        state = self.states[inter.guild.id]
        if not song:
            song = Song(inter.author)
            state.song_queue.append(song)
        if not "https://" in query:
            asyncio.create_task(self.select_song(inter, song, query))
        else:
            asyncio.create_task(self.add_from_url_to_queue(inter, song, query))

    async def add_from_url_to_queue(self, inter, song, url, respond=True):
        state = self.states[inter.guild.id]
        if "list" in url:
            await self.add_from_url_to_queue(inter, song, url[:url.find("list")-1])
            return self.add_from_playlist(inter, url)
        else:
            print("Downloading")
            with YoutubeDL(config.YTDL_OPTIONS) as ytdl:
                track_info = ytdl.extract_info(url, download=False)
            print("Downloaded")
            song.track_info.set_result(track_info)
            print(f"Added song: {track_info['webpage_url']}")
            if state.voice and (state.voice.is_playing() or state.voice.is_paused()):
                embed = self.embedder.songs(
                    song.author, track_info, "Song was added to queue!")
                song.original_message = await inter.text_channel.send("", embed=embed)
            if respond:
                await inter.orig_inter.delete_original_response()
            self.logger.added(state.guild, track_info)

    async def select_song(self, inter, song, query):
        songs = YoutubeSearch(query, max_results=5).to_dict()
        select = SelectionPanel(songs, self.add_from_url_to_queue, inter, song)
        await inter.orig_inter.delete_original_response()
        await select.send()

    def add_from_playlist(self, inter, url):
        state = self.states[inter.guild.id]
        print("Downloading")
        with YoutubeDL(config.YTDL_OPTIONS) as ytdl:
            playlist_info = ytdl.extract_info(url, download=False)
        print("Downloaded")
        # TODO: Proper condition for not adding
        if not state.voice:
            return
        for entry in playlist_info['entries'][1:]:
            song = Song(inter.author)
            song.track_info.set_result(entry)
            state.song_queue.append(song)
            print(f"Added song: {entry['webpage_url']}")

    async def play_loop(self, guild_id):
        state = self.states[guild_id]
        try:
            print(
                f"Voice in loop: {state.voice}, {bool (state.voice.is_connected())}")
            print("Entered play loop")
            while state.song_queue:
                current_song = state.song_queue.pop(0)
                current_track = await current_song.track_info
                if not current_track:
                    print(f"Invalid Track")
                    continue

                link = current_track.get("url", None)

                print(
                    f"Voice in loop: {state.voice}, {bool (state.voice.is_connected())}, connected to: {state.voice.channel.name}")
                print(f"Playing: {link}")
                state.voice.play(disnake.FFmpegPCMAudio(
                    source=link, **config.FFMPEG_OPTIONS))
                if current_song.original_message:
                    await current_song.original_message.delete()
                embed = self.embedder.songs(
                    current_song.author, current_track, "Playing this song!")
                await state.last_inter.text_channel.send("", embed=embed)
                await self.play_before_interrupt(guild_id)
                if not state.voice:
                    print("Leaving because not connected")
                    break

                if state.skip_flag:
                    print("Pausing voice because of skip")
                    state.voice.stop()
                    state.skip_flag = False
                elif state.repeat_flag:
                    state.song_queue.insert(
                        0, current_song)
            if not state.song_queue:
                print("Queue empty")
            await self.abort_play(guild_id)
        except Exception as err:
            print(f"Execption in play_loop: {err}")
            self.logger.error(err, state.guild)
            pass

    async def play_before_interrupt(self, guild_id):
        state = self.states[guild_id]
        try:
            while (state.voice and (state.voice.is_playing() or state.voice.is_paused()) and not state.skip_flag):
                await asyncio.sleep(1)
        except Exception as err:
            print(f"Caught exception in play_before_interrupt: {err}")

# *_______PlayerFuncs________________________________________________________________________________________________________________________________________

    # *Requires author of inter to be in voice channel
    async def play(self, inter, query, playnow=False):
        state = self.states[inter.guild.id]
        state.last_inter = inter

        if not state.voice:
            state.voice = await inter.voice_channel.connect()
            await self.process_song_query(inter, query)
            return asyncio.create_task(self.play_loop(inter.guild.id))

        if state.voice and inter.voice_channel == state.voice.channel:
            return await self.process_song_query(inter, query)

        if state.voice and inter.voice_channel != state.voice.channel:
            state.voice.stop()
            await self.cancel_timeout(inter.guild.id, False)
            state.reset()
            song = Song(inter.author)
            state.song_queue.append(song)
            print(f"Switching to: {inter.voice_channel.name}")
            await state.voice.move_to(inter.voice_channel)
            await state.connected_to(inter.voice_channel)
            print(f"Switched to: {state.voice.channel.name}")
            await self.process_song_query(inter, query, song=song)

    async def stop(self, inter):
        state = self.states[inter.guild.id]
        await inter.orig_inter.delete_original_response()
        if not state.voice:
            await inter.text_channel.send("Wrong instance to process operation")
            return

        await self.abort_play(inter.guild.id, message="DJ decided to stop!")

    async def pause(self, inter):
        state = self.states[inter.guild.id]
        await inter.orig_inter.delete_original_response()
        if not state.voice:
            await inter.text_channel.send("Wrong instance to process operation")
            return
        if state.paused:
            state.paused = False
            if state.voice.is_paused():
                state.voice.resume()
            await inter.text_channel.send("Player resumed!")
        else:
            state.paused = True
            if state.voice.is_playing():
                state.voice.pause()
            await inter.text_channel.send("Player paused!")

    async def repeat(self, inter):
        state = self.states[inter.guild.id]
        await inter.orig_inter.delete_original_response()
        if not state.voice:
            await inter.text_channel.send("Wrong instance to process operation")
            return

        if state.repeat_flag:
            state.repeat_flag = False
            await inter.text_channel.send("Repeat mode is off!")
        else:
            state.repeat_flag = True
            await inter.text_channel.send("Repeat mode is on!")

    async def skip(self, inter):
        state = self.states[inter.guild.id]
        await inter.orig_inter.delete_original_response()
        if not state.voice:
            await inter.text_channel.send("Wrong instance to process operation")
            return
        state.skip_flag = True
        await inter.text_channel.send("Skipped current track!")

    async def queue(self, inter):
        state = self.states[inter.guild.id]
        await inter.orig_inter.delete_original_response()
        if not state.voice:
            await inter.text_channel.send("Wrong instance to process operation")
            return

        if len(state.song_queue) > 0:
            cnt = 1
            ans = "```Queue:"
            for song in state.song_queue[:15]:
                # TODO: Maybe show that song being loaded
                if not song.track_info.done():
                    continue
                track = song.track_info.result()
                if "live_status" in track and track['live_status'] == "is_live":
                    duration = "Live"
                else:
                    duration = helpers.get_duration(track)
                ans += f"\n{cnt}) {track['title']}, duration: {duration}"
                cnt += 1
            ans += "```"
            await inter.text_channel.send(ans)
        else:
            await inter.text_channel.send("There are no songs in the queue!")

    async def wrong(self, inter):
        state = self.states[inter.guild.id]
        await inter.orig_inter.delete_original_response()
        if not state.voice:
            await inter.text_channel.send("Wrong instance to process operation")
            return

        if len(state.song_queue) > 0:
            title = "(Not yet loaded)"
            song = state.song_queue[-1]
            state.song_queue.pop(-1)
            if song.track_info.done():
                title = song.track_info.result()['title']
            await inter.text_channel.send(f"Removed {title} from queue!")
        else:
            await inter.text_channel.send("There are no songs in the queue!")

    async def shuffle(self, inter):
        state = self.states[inter.guild.id]
        await inter.orig_inter.delete_original_response()
        if not state.voice:
            await inter.text_channel.send("Wrong instance to process operation")
            return

        if len(state.song_queue) > 1:
            random.shuffle(state.song_queue)
            await inter.text_channel.send("Shuffle completed successfully!")
        elif len(state.song_queue) == 1:
            await inter.text_channel.send("There are no tracks to shuffle!")
        else:
            await inter.text_channel.send("I am not playing anything!")
