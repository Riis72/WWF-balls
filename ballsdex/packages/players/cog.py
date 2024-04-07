import enum
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, cast

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View, button
from tortoise.exceptions import DoesNotExist

from ballsdex.core.models import BallInstance, DonationPolicy, Player, Trade, TradeObject, balls
from ballsdex.core.utils.paginator import FieldPageSource, Pages
from ballsdex.core.utils.transformers import (
    BallEnabledTransform,
    BallInstanceTransform,
    SpecialEnabledTransform,
)
from ballsdex.packages.players.countryballs_paginator import CountryballsViewer
from ballsdex.settings import settings

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.packages.countryballs")


class DonationRequest(View):
    def __init__(
        self,
        bot: "BallsDexBot",
        interaction: discord.Interaction,
        countryball: BallInstance,
        new_player: Player,
    ):
        super().__init__(timeout=120)
        self.bot = bot
        self.original_interaction = interaction
        self.countryball = countryball
        self.new_player = new_player

    async def interaction_check(self, interaction: discord.Interaction, /) -> bool:
        if interaction.user.id != self.new_player.discord_id:
            await interaction.response.send_message(
                "You are not allowed to interact with this menu.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True  # type: ignore
        try:
            await self.original_interaction.followup.edit_message(
                "@original", view=self  # type: ignore
            )
        except discord.NotFound:
            pass
        del self.bot.locked_balls[self.countryball.pk]

    @button(
        style=discord.ButtonStyle.success, emoji="\N{HEAVY CHECK MARK}\N{VARIATION SELECTOR-16}"
    )
    async def accept(self, interaction: discord.Interaction, button: Button):
        self.stop()
        for item in self.children:
            item.disabled = True  # type: ignore
        self.countryball.trade_player = self.countryball.player
        self.countryball.player = self.new_player
        await self.countryball.save()
        await interaction.response.edit_message(
            content=interaction.message.content  # type: ignore
            + "\n\N{WHITE HEAVY CHECK MARK} The donation was accepted!",
            view=self,
        )
        del self.bot.locked_balls[self.countryball.pk]

    @button(
        style=discord.ButtonStyle.danger,
        emoji="\N{HEAVY MULTIPLICATION X}\N{VARIATION SELECTOR-16}",
    )
    async def deny(self, interaction: discord.Interaction, button: Button):
        self.stop()
        for item in self.children:
            item.disabled = True  # type: ignore
        await interaction.response.edit_message(
            content=interaction.message.content  # type: ignore
            + "\n\N{CROSS MARK} The donation was denied.",
            view=self,
        )
        del self.bot.locked_balls[self.countryball.pk]


class SortingChoices(enum.Enum):
    alphabetic = "ball__country"
    catch_date = "-catch_date"
    rarity = "ball__rarity"
    special = "special__id"
    health = "health"
    attack = "attack"
    health_bonus = "-health_bonus"
    attack_bonus = "-attack_bonus"
    stats_bonus = "stats"
    total_stats = "total_stats"

    # manual sorts are not sorted by SQL queries but by our code
    # this may be do-able with SQL still, but I don't have much experience ngl
    duplicates = "manualsort-duplicates"


class Players(commands.GroupCog, group_name=settings.players_group_cog_name):
    """
    View and manage your countryballs collection.
    """

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot

    @app_commands.command()
    @app_commands.checks.cooldown(1, 10, key=lambda i: i.user.id)
    async def list(
        self,
        interaction: discord.Interaction["BallsDexBot"],
        user: discord.Member | None = None,
        sort: SortingChoices | None = None,
        reverse: bool = False,
    ):
        """
        List your countryballs.

        Parameters
        ----------
        user: discord.User
            The user whose collection you want to view, if not yours.
        sort: SortingChoices
            Choose how countryballs are sorted. Can be used to show duplicates.
        reverse: bool
            Reverse the output of the list.
        """
        user_obj = user or interaction.user
        await interaction.response.defer(thinking=True)

        try:
            player = await Player.get(discord_id=user_obj.id)
        except DoesNotExist:
            if user_obj == interaction.user:
                await interaction.followup.send(
                    f"You don't have any {settings.collectible_name} yet."
                )
            else:
                await interaction.followup.send(
                    f"{user_obj.name} doesn't have any {settings.collectible_name} yet."
                )
            return

        await player.fetch_related("balls")
        if sort:
            if sort == SortingChoices.duplicates:
                countryballs = await player.balls.all()
                count = defaultdict(int)
                for countryball in countryballs:
                    count[countryball.countryball.pk] += 1
                countryballs.sort(key=lambda m: (-count[m.countryball.pk], m.countryball.pk))
            elif sort == SortingChoices.stats_bonus:
                countryballs = await player.balls.all()
                countryballs.sort(key=lambda x: (x.health_bonus, x.attack_bonus), reverse=True)
            elif sort == SortingChoices.health or sort == SortingChoices.attack:
                countryballs = await player.balls.all()
                countryballs.sort(key=lambda x: getattr(x, sort.value), reverse=True)
            elif sort == SortingChoices.total_stats:
                countryballs = await player.balls.all()
                countryballs.sort(key=lambda x: (x.health, x.attack), reverse=True)
            else:
                countryballs = await player.balls.all().order_by(sort.value)
        else:
            countryballs = await player.balls.all().order_by("-favorite", "-shiny")

        if len(countryballs) < 1:
            if user_obj == interaction.user:
                await interaction.followup.send(
                    f"You don't have any {settings.collectible_name} yet."
                )
            else:
                await interaction.followup.send(
                    f"{user_obj.name} doesn't have any {settings.collectible_name} yet."
                )
            return
        if reverse:
            countryballs.reverse()

        paginator = CountryballsViewer(interaction, countryballs)
        if user_obj == interaction.user:
            await paginator.start()
        else:
            await paginator.start(
                content=f"Viewing {user_obj.name}'s {settings.collectible_name}s"
            )

    @app_commands.command()
    async def milloin(self,
    interaction: discord.Interaction,
    guild_id: str | None = None
    ):
        guild = interaction.guild
        spawn_manager = cast(
            "CountryBallsSpawner", self.bot.get_cog("CountryBallsSpawner")
        ).spawn_manager
        cooldown = spawn_manager.cooldowns.get(guild.id)

        embed = discord.Embed()
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else none)
        embed.colour = discord.Colour.orange()

        delta = (interaction.created_at - cooldown.time).total_seconds()
        # change how the threshold varies according to the member count, while nuking farm servers
        if guild.member_count < 5:
            multiplier = 0.1
            range = "1-4"
        elif guild.member_count < 100:
            multiplier = 0.8
            range = "5-99"
        elif guild.member_count < 1000:
            multiplier = 0.5
            range = "100-999"
        else:
            multiplier = 0.2
            range = "1000+"
        chance = cooldown.chance - multiplier * (delta // 60)

        embed.description = (
            f"**Cooldown:** {cooldown.amount}/{chance}\n"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command()
    @app_commands.checks.cooldown(1, 60, key=lambda i: i.user.id)
    async def completion(
            self,
            interaction: discord.Interaction["BallsDexBot"],
            user: discord.User | None = None,
            special: SpecialEnabledTransform | None = None,
            shiny: bool | None = None,
    ):
        """
        Show your current completion of the BallsDex.

        Parameters
        ----------
        user: discord.User
            The user whose completion you want to view, if not yours.
        """
        user_obj = user or interaction.user
        # Filter disabled balls, they do not count towards progression
        # Only ID and emoji is interesting for us
        bot_countryballs = {x: y.emoji_id for x, y in balls.items() if y.enabled}

        filters = {"player__discord_id": user_obj.id, "ball__enabled": True}
        if special:
            filters["special"] = special
            bot_countryballs = {
                x: y.emoji_id
                for x, y in balls.items()
                if y.enabled and y.created_at < special.end_date
            }

        if not bot_countryballs:
            await interaction.response.send_message(
                f"There are no {settings.collectible_name}s registered on this bot yet.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True)

        if shiny is not None:
            filters["shiny"] = shiny

        owned_countryballs = set(
            x[0]
            for x in await BallInstance.filter(**filters)
            .distinct()  # Do not query everything
            .values_list("ball_id")
        )

        entries: list[tuple[str, str]] = []

        def fill_fields(title: str, emoji_ids: set[int]):
            # check if we need to add "(continued)" to the field name
            first_field_added = False
            buffer = ""

            for emoji_id in emoji_ids:
                emoji = self.bot.get_emoji(emoji_id)
                if not emoji:
                    continue

                text = f"{emoji} "
                if len(buffer) + len(text) > 1024:
                    # hitting embed limits, adding an intermediate field
                    if first_field_added:
                        entries.append(("\u200B", buffer))
                    else:
                        entries.append((f"__**{title}**__", buffer))
                        first_field_added = True
                    buffer = ""
                buffer += text

            if buffer:  # add what's remaining
                if first_field_added:
                    entries.append(("\u200B", buffer))
                else:
                    entries.append((f"__**{title}**__", buffer))

        if owned_countryballs:
            # Getting the list of emoji IDs from the IDs of the owned countryballs
            fill_fields(
                f"Owned {settings.collectible_name}s",
                set(bot_countryballs[x] for x in owned_countryballs),
            )
        else:
            entries.append((f"__**Owned {settings.collectible_name}s**__", "Nothing yet."))

        if missing := set(y for x, y in bot_countryballs.items() if x not in owned_countryballs):
            fill_fields(f"Missing {settings.collectible_name}s", missing)
        else:
            entries.append(
                (
                    f"__**:tada: No missing {settings.collectible_name}, "
                    "congratulations! :tada:**__",
                    "\u200B",
                )
            )  # force empty field value

        source = FieldPageSource(entries, per_page=5, inline=False, clear_description=False)
        special_str = f" ({special.name})" if special else ""
        shiny_str = " shiny" if shiny else ""
        source.embed.description = (
            f"{settings.bot_name}{special_str}{shiny_str} progression: "
            f"**{round(len(owned_countryballs)/len(bot_countryballs)*100, 1)}%**"
        )
        source.embed.colour = discord.Colour.blurple()
        source.embed.set_author(name=user_obj.display_name, icon_url=user_obj.display_avatar.url)

        pages = Pages(source=source, interaction=interaction, compact=True)
        await pages.start()

    @app_commands.command()
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def info(self, interaction: discord.Interaction, countryball: BallInstanceTransform):
        """
        Display info from a specific countryball.

        Parameters
        ----------
        countryball: BallInstance
            The countryball you want to inspect
        """
        if not countryball:
            return
        await interaction.response.defer(thinking=True)
        content, file = await countryball.prepare_for_message(interaction)
        await interaction.followup.send(content=content, file=file)
        file.close()

    @app_commands.command()
    @app_commands.checks.cooldown(1, 60, key=lambda i: i.user.id)
    async def last(self, interaction: discord.Interaction, user: discord.Member | None = None):
        """
        Display info of your or another users last caught countryball.

        Parameters
        ----------
        user: discord.Member
            The user you would like to see
        """
        user_obj = user if user else interaction.user
        await interaction.response.defer(thinking=True)
        try:
            player = await Player.get(discord_id=user_obj.id)
        except DoesNotExist:
            msg = f"{'You do' if user is None else f'{user_obj.display_name} does'}"
            await interaction.followup.send(
                f"{msg} not have any {settings.collectible_name} yet.",
                ephemeral=True,
            )
            return

        countryball = await player.balls.all().order_by("-id").first().select_related("ball")
        if not countryball:
            msg = f"{'You do' if user is None else f'{user_obj.display_name} does'}"
            await interaction.followup.send(
                f"{msg} not have any {settings.collectible_name} yet.",
                ephemeral=True,
            )
            return

        content, file = await countryball.prepare_for_message(interaction)
        await interaction.followup.send(content=content, file=file)
        file.close()

    @app_commands.command()
    async def favorite(self, interaction: discord.Interaction, countryball: BallInstanceTransform):
        """
        Set favorite countryballs.

        Parameters
        ----------
        countryball: BallInstance
            The countryball you want to set/unset as favorite
        """
        if not countryball:
            return

        if not countryball.favorite:
            player = await Player.get(discord_id=interaction.user.id).prefetch_related("balls")
            if await player.balls.filter(favorite=True).count() > 20:
                await interaction.response.send_message(
                    f"You cannot set more than 20 favorite {settings.collectible_name}s.",
                    ephemeral=True,
                )
                return

            countryball.favorite = True  # type: ignore
            await countryball.save()
            emoji = self.bot.get_emoji(countryball.countryball.emoji_id) or ""
            await interaction.response.send_message(
                f"{emoji} `#{countryball.pk:0X}` {countryball.countryball.country} "
                f"is now a favorite {settings.collectible_name}!",
                ephemeral=True,
            )

        else:
            countryball.favorite = False  # type: ignore
            await countryball.save()
            emoji = self.bot.get_emoji(countryball.countryball.emoji_id) or ""
            await interaction.response.send_message(
                f"{emoji} `#{countryball.pk:0X}` {countryball.countryball.country} "
                f"isn't a favorite {settings.collectible_name} anymore.",
                ephemeral=True,
            )

    @app_commands.command()
    @app_commands.choices(
        policy=[
            app_commands.Choice(name="Accept all donations", value=DonationPolicy.ALWAYS_ACCEPT),
            app_commands.Choice(
                name="Request your approval first", value=DonationPolicy.REQUEST_APPROVAL
            ),
            app_commands.Choice(name="Deny all donations", value=DonationPolicy.ALWAYS_DENY),
        ]
    )
    async def donation_policy(
        self, interaction: discord.Interaction, policy: app_commands.Choice[int]
    ):
        """
        Change how you want to receive donations from /balls give

        Parameters
        ----------
        policy: DonationPolicy
            The new policy for accepting donations
        """
        player, _ = await Player.get_or_create(discord_id=interaction.user.id)
        player.donation_policy = DonationPolicy(policy.value)
        if policy.value == DonationPolicy.ALWAYS_ACCEPT:
            await interaction.response.send_message(
                f"Setting updated, you will now receive all donated {settings.collectible_name}s "
                "immediately."
            )
        elif policy.value == DonationPolicy.REQUEST_APPROVAL:
            await interaction.response.send_message(
                "Setting updated, you will now have to approve donation requests manually."
            )
        elif policy.value == DonationPolicy.ALWAYS_DENY:
            await interaction.response.send_message(
                f"Setting updated, it is now impossible to use {self.give.extras['mention']} with "
                "you. It is still possible to perform donations using the trade system."
            )
        else:
            await interaction.response.send_message("Invalid input!")
            return
        await player.save()  # do not save if the input is invalid

    @app_commands.command()
    async def give(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        countryball: BallInstanceTransform,
    ):
        """
        Give a countryball to a user.

        Parameters
        ----------
        user: discord.User
            The user you want to give a countryball to
        countryball: BallInstance
            The countryball you're giving away
        """
        if not countryball:
            return
        if not countryball.is_tradeable:
            await interaction.response.send_message(
                "You cannot donate this countryball.", ephemeral=True
            )
            return
        if user.bot:
            await interaction.response.send_message("You cannot donate to bots.")
            return
        if countryball.pk in self.bot.locked_balls:
            await interaction.response.send_message(
                "This countryball is currently locked for a trade. Please try again later."
            )
            return
        self.bot.locked_balls[countryball.pk] = None
        new_player, _ = await Player.get_or_create(discord_id=user.id)
        old_player = countryball.player

        if new_player == old_player:
            await interaction.response.send_message(
                f"You cannot give a {settings.collectible_name} to yourself."
            )
            del self.bot.locked_balls[countryball.pk]
            return
        if new_player.donation_policy == DonationPolicy.ALWAYS_DENY:
            await interaction.response.send_message(
                "This player does not accept donations. You can use trades instead."
            )
            del self.bot.locked_balls[countryball.pk]
            return
        if new_player.discord_id in self.bot.blacklist:
            await interaction.response.send_message(
                "You cannot donate to a blacklisted user", ephemeral=True
            )
            del self.bot.locked_balls[countryball.pk]
            return
        elif new_player.donation_policy == DonationPolicy.REQUEST_APPROVAL:
            await interaction.response.send_message(
                f"Hey {user.mention}, {interaction.user.name} wants to give you "
                f"{countryball.description(include_emoji=True, bot=interaction.client)}!\n"
                "Do you accept this donation?",
                view=DonationRequest(self.bot, interaction, countryball, new_player),
            )
            return

        countryball.player = new_player
        countryball.trade_player = old_player
        countryball.favorite = False
        await countryball.save()

        trade = await Trade.create(player1=old_player, player2=new_player)
        await TradeObject.create(trade=trade, ballinstance=countryball, player=old_player)

        await interaction.response.send_message(
            f"You just gave the {settings.collectible_name} "
            f"{countryball.description(short=True, include_emoji=True, bot=self.bot)} to "
            f"{user.mention}!"
        )
        del self.bot.locked_balls[countryball.pk]

    @app_commands.command()
    async def count(
        self,
        interaction: discord.Interaction,
        countryball: BallEnabledTransform | None = None,
        special: SpecialEnabledTransform | None = None,
        shiny: bool | None = None,
        current_server: bool = False,
    ):
        """
        Count how many countryballs you have.

        Parameters
        ----------
        countryball: Ball
            The countryball you want to count
        special: Special
            The special you want to count
        shiny: bool
            Whether you want to count shiny countryballs
        current_server: bool
            Only count countryballs caught in the current server
        """
        if interaction.response.is_done():
            return
        assert interaction.guild
        filters = {}
        if countryball:
            filters["ball"] = countryball
        if shiny is not None:
            filters["shiny"] = shiny
        if special:
            filters["special"] = special
        if current_server:
            filters["server_id"] = interaction.guild.id
        filters["player__discord_id"] = interaction.user.id
        await interaction.response.defer(ephemeral=True, thinking=True)
        balls = await BallInstance.filter(**filters).count()
        country = f"{countryball.country} " if countryball else ""
        plural = "s" if balls > 1 or balls == 0 else ""
        shiny_str = "shiny" if shiny else ""
        special_str = f"{special.name} " if special else ""
        guild = f" caught in {interaction.guild.name}" if current_server else ""
        await interaction.followup.send(
            f"You have {balls} {special_str}{shiny_str}"
            f"{country}{settings.collectible_name}{plural}{guild}."
        )
