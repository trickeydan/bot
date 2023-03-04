from datetime import datetime, timedelta
from logging import getLogger

import discord
from discord.app_commands import Group, command

from kmibot.config import BotConfig, PubInfo

from .views import PubView

LOGGER = getLogger(__name__)


class PubCommand(Group):

    def __init__(self, config: BotConfig) -> None:
        super().__init__(name="pub", description="Manage the pub event")
        self.config = config

    def _event_is_pub(self, event: discord.ScheduledEvent) -> bool:
        return "Pub" in event.name

    async def _choose_pub(
        self, interaction: discord.Interaction, prompt: str,
    ) -> PubInfo:
        view = PubView(self.config.pub, prompt)
        await interaction.response.send_message(
            prompt,
            view=view,
            ephemeral=True,
        )
        pub = await view.wait_until_complete()
        LOGGER.info(f"{interaction.user} chose {pub.name}")
        return pub

    def _get_next_pub_time(self) -> datetime:
        now = datetime.now(tz=self.config.timezone)
        today = now.date()
        if today.weekday() < self.config.pub.weekday or (
            today.weekday() == self.config.pub.weekday
            and (now.hour, now.minute) < (self.config.pub.hour, self.config.pub.minute)  # noqa: E501,W503
        ):
            # The pub has not yet happened
            monday = today - timedelta(days=today.weekday())
        else:
            # The pub has already happened, look at next week
            monday = today + timedelta(days=7 - today.weekday())
        pubday = monday + timedelta(days=self.config.pub.weekday)

        return datetime(
            pubday.year,
            pubday.month,
            pubday.day,
            self.config.pub.hour,
            self.config.pub.minute,
            tzinfo=self.config.timezone,
        )

    def _get_next_event(self, guild: discord.Guild) -> discord.ScheduledEvent | None:
        pub_time = self._get_next_pub_time()
        for event in guild.scheduled_events:
            if self._event_is_pub(event) and event.start_time == pub_time:
                return event
        return None

    async def _create_pub_event(
        self,
        guild: discord.Guild,
        pub: PubInfo,
        start_time: datetime,
        *,
        user: str = "A user",
        title: str = "Pub",
    ) -> discord.ScheduledEvent:
        LOGGER.info(f"Creating scheduled event at {start_time}")
        return await guild.create_scheduled_event(
            name=f"{pub.emoji} {title} {pub.emoji}",
            start_time=start_time,
            end_time=start_time + timedelta(hours=3),
            location=pub.name,
            description=self.config.pub.description,
            reason=f"{user} used the /pub next command",
        )

    def _get_pub_buttons_view(self, pub: PubInfo) -> discord.ui.View:
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Map", url=pub.map_url))
        if pub.menu_url:
            view.add_item(discord.ui.Button(label="Menu", url=pub.menu_url))
        return view

    @command(description="Get information about the pub.")  # type: ignore[arg-type]
    async def info(self, interaction: discord.Interaction) -> None:
        LOGGER.info(f"{interaction.user} used /pub info")
        assert interaction.guild is not None
        pub_event = self._get_next_event(interaction.guild)
        if pub_event is None:
            LOGGER.info("There is no scheduled pub.")
            await interaction.response.send_message(
                "There is no pub scheduled",
                ephemeral=True,
            )
        else:
            pub = discord.utils.find(
                lambda p: pub_event and p.name == pub_event.location,
                self.config.pub.pubs,
            )

            if pub is None:
                await interaction.response.send_message(
                    f"No information about {pub_event.location}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "\n".join(
                        [
                            "**Pub Next Week**",
                            f"The next pub will be <t:{int(pub_event.start_time.timestamp())}:R>",  # noqa: E501
                            f"It will be held at {pub.emoji} **{pub.name}** {pub.emoji}",
                            "",
                            "If you are coming, please mark 🔔 interest on the event!",
                        ],
                    ),
                    view=self._get_pub_buttons_view(pub),
                    ephemeral=True,
                )

    @command(description="Select the pub for next week.")  # type: ignore[arg-type]
    async def next(self, interaction: discord.Interaction) -> None:  # noqa: A003
        LOGGER.info(f"{interaction.user} used /pub next")
        assert interaction.guild is not None

        if self._get_next_event(interaction.guild):
            LOGGER.info("A pub event already exists.")
            await interaction.response.send_message(
                "A pub event already exists.",
                ephemeral=True,
            )
            return

        pub_time = self._get_next_pub_time()

        pub = await self._choose_pub(
            interaction,
            f"Please choose the pub for {pub_time}",
        )

        pub_channel = interaction.guild.get_channel(self.config.pub.channel_id)
        assert isinstance(pub_channel, discord.TextChannel)

        if pub.fake:
            await pub_channel.send(
                f"Oi <@{pub.fake}>, can we go to {pub.name} next week?",
                view=self._get_pub_buttons_view(pub),
            )
        else:
            await self._create_pub_event(
                interaction.guild,
                pub,
                pub_time,
                user=interaction.user.name,
            )

            LOGGER.info(f"Posting pub info in {pub_channel}")
            await pub_channel.send(
                "\n".join(
                    [
                        "**Pub Next Week**",
                        f"The next pub will be <t:{int(pub_time.timestamp())}:R>",
                        f"It will be held at {pub.emoji} **{pub.name}** {pub.emoji}",
                        "",
                        "If you are coming, please mark 🔔 interest on the event!",
                    ],
                ),
                view=self._get_pub_buttons_view(pub),
            )

    @command(description="Announce a spontaneous pub event.")  # type: ignore[arg-type]
    async def now(self, interaction: discord.Interaction) -> None:
        LOGGER.info(f"{interaction.user} used /pub now")
        pub = await self._choose_pub(
            interaction,
            "Please choose the spontaneous pub",
        )
        now = datetime.now(tz=self.config.timezone)
        pub_time = now + timedelta(seconds=1)
        assert interaction.guild is not None

        pub_channel = interaction.guild.get_channel(self.config.pub.channel_id)
        assert isinstance(pub_channel, discord.TextChannel)

        if pub.fake:
            await pub_channel.send(
                f"Oi <@{pub.fake}>, can we go to {pub.name}?",
                view=self._get_pub_buttons_view(pub),
            )
        else:
            await self._create_pub_event(
                interaction.guild,
                pub,
                pub_time,
                user=interaction.user.name,
                title="Spontaneous Pub",
            )

            await pub_channel.send(
                "\n".join(
                    [
                        "**Pub Right Now**",
                        f"There is a pub right now: <t:{int(pub_time.timestamp())}:R>",
                        f"It is being held at {pub.emoji} **{pub.name}** {pub.emoji}",
                        "",
                        "If you are coming, please don't waste time marking 🔔 interest"
                        " on the event, just go immediately!",
                    ],
                ),
                view=self._get_pub_buttons_view(pub),
            )