import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random
import os
from datetime import datetime, timedelta, timezone

TOKEN = os.environ.get("TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

giveaways = {}


def parse_duration(duration_str: str):
    duration_str = duration_str.strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    for unit, multiplier in units.items():
        if duration_str.endswith(unit):
            try:
                return int(duration_str[:-1]) * multiplier
            except ValueError:
                return None
    try:
        return int(duration_str)
    except ValueError:
        return None


def now_utc():
    return datetime.now(timezone.utc)


def build_giveaway_embed(prize, winners_count, host, end_time, ended=False, winner_names=None):
    if ended:
        color = discord.Color.red()
        end_field_name = "⏰ Encerrado"
        end_field_value = f"<t:{int(end_time.timestamp())}:R>"
        winners_value = ", ".join(winner_names) if winner_names else "Nenhum participante"
    else:
        color = discord.Color.gold()
        end_field_name = "⏰ Termina"
        end_field_value = f"<t:{int(end_time.timestamp())}:R>"
        winners_value = str(winners_count)

    embed = discord.Embed(title=f"🎉 {prize} 🎉", color=color)
    embed.add_field(name="🏆 Ganhadores:", value=winners_value, inline=True)
    embed.add_field(name="👑 Criado por:", value=host.mention, inline=True)
    embed.add_field(name=end_field_name, value=end_field_value, inline=False)
    embed.set_footer(text="Sorteio encerrado!" if ended else "Clique no botão 🎉 para participar!")

    return embed


def build_winner_embed(prize, winner_mentions):
    embed = discord.Embed(
        title=f"🏆 {prize}",
        color=discord.Color.green()
    )
    embed.add_field(
        name="🎉 Ganhador(es):",
        value=", ".join(winner_mentions) if winner_mentions else "Nenhum participante",
        inline=False
    )
    embed.set_footer(text="Parabéns ao(s) ganhador(es)!")
    return embed


class JoinGiveawayView(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self._rebuild_button()

    def _rebuild_button(self):
        self.clear_items()
        gw = giveaways.get(self.giveaway_id)
        count = len(gw["participants"]) if gw else 0
        btn = discord.ui.Button(
            label=f"🎉 {count}",
            style=discord.ButtonStyle.primary,
            custom_id=f"join_{self.giveaway_id}"
        )
        btn.callback = self.join_callback
        self.add_item(btn)

    async def join_callback(self, interaction: discord.Interaction):
        gw = giveaways.get(self.giveaway_id)
        if not gw:
            await interaction.response.send_message("❌ Sorteio não encontrado!", ephemeral=True)
            return
        if gw["ended"]:
            await interaction.response.send_message("❌ Este sorteio já acabou!", ephemeral=True)
            return

        user_id = interaction.user.id

        if user_id in gw["participants"]:
            view = LeaveGiveawayView(self.giveaway_id, interaction.user)
            await interaction.response.send_message(
                f"⚠️ Você já está participando do sorteio **{gw['prize']}**!\nDeseja sair?",
                view=view,
                ephemeral=True
            )
        else:
            gw["participants"].add(user_id)
            self._rebuild_button()
            await interaction.message.edit(view=self)
            await interaction.response.send_message(
                f"✅ Você agora está participando do sorteio **{gw['prize']}**! Boa sorte! 🍀",
                ephemeral=True
            )


class LeaveGiveawayView(discord.ui.View):
    def __init__(self, giveaway_id, user):
        super().__init__(timeout=60)
        self.giveaway_id = giveaway_id
        self.user = user

    @discord.ui.button(label="Sair do Sorteio ❌", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ Isso não é pra você!", ephemeral=True)
            return

        gw = giveaways.get(self.giveaway_id)
        if gw and interaction.user.id in gw["participants"]:
            gw["participants"].discard(interaction.user.id)

            channel = bot.get_channel(gw["channel_id"])
            if channel:
                try:
                    msg = await channel.fetch_message(self.giveaway_id)
                    new_view = JoinGiveawayView(self.giveaway_id)
                    await msg.edit(view=new_view)
                except Exception:
                    pass

            await interaction.response.edit_message(
                content="✅ Você saiu do sorteio com sucesso!", view=None)
        else:
            await interaction.response.edit_message(
                content="❌ Você não estava participando.", view=None)


class GiveawayGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="sorteio", description="Comandos de sorteio")

    @app_commands.command(name="criar", description="Cria um novo sorteio")
    @app_commands.describe(
        duracao="Duração do sorteio (ex: 10s, 5m, 2h, 1d)",
        ganhadores="Número de ganhadores",
        premio="Prêmio do sorteio (ex: Nitro Discord)",
        canal="Canal onde o sorteio será realizado"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def criar(
        self,
        interaction: discord.Interaction,
        duracao: str,
        ganhadores: int,
        premio: str,
        canal: discord.TextChannel
    ):
        seconds = parse_duration(duracao)
        if not seconds or seconds <= 0:
            await interaction.response.send_message(
                "❌ Duração inválida! Use: `10s`, `5m`, `2h`, `1d`", ephemeral=True
            )
            return

        if ganhadores < 1:
            await interaction.response.send_message(
                "❌ O número de ganhadores deve ser pelo menos 1!", ephemeral=True
            )
            return

        end_time = now_utc() + timedelta(seconds=seconds)
        embed = build_giveaway_embed(premio, ganhadores, interaction.user, end_time)

        await canal.send("🎉 **Sorteio Iniciado** 🎉")
        giveaway_msg = await canal.send(embed=embed)

        giveaways[giveaway_msg.id] = {
            "prize": premio,
            "winners_count": ganhadores,
            "host": interaction.user,
            "end_time": end_time,
            "channel_id": canal.id,
            "participants": set(),
            "ended": False
        }

        real_view = JoinGiveawayView(giveaway_msg.id)
        await giveaway_msg.edit(view=real_view)

        await interaction.response.send_message(
            f"✅ Sorteio criado em {canal.mention}!", ephemeral=True)
        bot.loop.create_task(end_giveaway_after(giveaway_msg.id, seconds))

    @criar.error
    async def criar_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ Você precisa ser **Administrador** para criar sorteios!", ephemeral=True
            )


async def end_giveaway_after(message_id, delay):
    await asyncio.sleep(delay)
    await finish_giveaway(message_id)


async def finish_giveaway(message_id):
    gw = giveaways.get(message_id)
    if not gw or gw["ended"]:
        return

    gw["ended"] = True
    channel = bot.get_channel(gw["channel_id"])
    if not channel:
        return

    participants = list(gw["participants"])
    winners_count = min(gw["winners_count"], len(participants))

    if participants:
        winner_ids = random.sample(participants, winners_count)
        winner_names = []
        winner_mentions = []
        for wid in winner_ids:
            member = channel.guild.get_member(wid)
            if member:
                winner_names.append(member.display_name)
                winner_mentions.append(member.mention)
    else:
        winner_names = []
        winner_mentions = []

    ended_embed = build_giveaway_embed(
        gw["prize"], gw["winners_count"], gw["host"],
        gw["end_time"], ended=True,
        winner_names=winner_mentions if winner_mentions else None
    )

    try:
        msg = await channel.fetch_message(message_id)
        await msg.edit(embed=ended_embed, view=None)
    except Exception:
        pass

    if winner_mentions:
        winner_embed = build_winner_embed(gw["prize"], winner_mentions)
        congrats_lines = "\n".join(
            [f"🎊 Parabéns {mention}, você ganhou o sorteio **{gw['prize']}**!" for mention in winner_mentions]
        )
        await channel.send(
            content=f"🎉 **Sorteio Encerrado** 🎉\n{congrats_lines}",
            embed=winner_embed
        )
    else:
        await channel.send(
            "🎉 **Sorteio Encerrado** 🎉\n😢 Ninguém participou do sorteio."
        )


@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    try:
        bot.tree.add_command(GiveawayGroup())
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} comando(s) sincronizado(s)!")
    except Exception as e:
        print(f"❌ Erro ao sincronizar: {e}")


bot.run(TOKEN)
