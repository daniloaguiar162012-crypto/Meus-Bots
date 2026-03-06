import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
from datetime import datetime, timezone, timedelta

TOKEN = os.environ.get("TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

ticket_configs = {}
open_tickets = {}
painel_messages = {}

DEFAULT_CONFIG = {
    "canal_id": None,
    "mensagem": "📩 Clique no botão abaixo para abrir um ticket!",
    "cor": 0xFF8C00,
    "imagem_grande": None,
    "imagem_pequena": None,
    "cargo_id": None,
}

BRASILIA = timezone(timedelta(hours=-3))


def get_config(guild_id):
    if guild_id not in ticket_configs:
        ticket_configs[guild_id] = DEFAULT_CONFIG.copy()
    return ticket_configs[guild_id]


def cor_hex_valida(hex_str: str):
    hex_str = hex_str.strip().lstrip("#")
    try:
        return int(hex_str, 16)
    except ValueError:
        return None


def tickets_abertos_agora():
    """Aberto das 12:00 até 23:59 | Fechado das 00:00 até 11:59 (horário de Brasília)"""
    agora = datetime.now(BRASILIA)
    return 12 <= agora.hour <= 23


def proximo_evento_timestamp():
    """Retorna o timestamp Unix do próximo abrir/fechar"""
    agora = datetime.now(BRASILIA)
    if tickets_abertos_agora():
        # Próximo evento = fechar às 00:00 de amanhã
        proximo = agora.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    else:
        # Próximo evento = abrir às 12:00 de hoje
        proximo = agora.replace(hour=12, minute=0, second=0, microsecond=0)
        if agora >= proximo:
            proximo += timedelta(days=1)
    return int(proximo.timestamp())


def build_painel_embed_view(guild_id, aberto, cfg):
    ts = proximo_evento_timestamp()
    if aberto:
        embed = discord.Embed(
            description=f"{cfg['mensagem']}\n\n🔒 Tickets fecham <t:{ts}:R> — <t:{ts}:t>",
            color=cfg["cor"]
        )
    else:
        embed = discord.Embed(
            description=f"🔒 **Os tickets estão fechados no momento.**\n\n✅ Abrirão <t:{ts}:R> — <t:{ts}:t>",
            color=discord.Color.red()
        )
    if cfg["imagem_grande"]:
        embed.set_image(url=cfg["imagem_grande"])
    if cfg["imagem_pequena"]:
        embed.set_thumbnail(url=cfg["imagem_pequena"])

    view = AbrirTicketView(guild_id, aberto)
    return embed, view


# ─────────────────────────────────────────────
#   TASK: Verifica horário a cada minuto
# ─────────────────────────────────────────────

@tasks.loop(minutes=1)
async def verificar_horario():
    agora = datetime.now(BRASILIA)
    # Atualiza exatamente às 00:00 (fecha) e 12:00 (abre)
    if agora.minute == 0 and agora.hour in (0, 12):
        aberto = tickets_abertos_agora()
        for guild_id, dados in list(painel_messages.items()):
            guild = bot.get_guild(guild_id)
            if not guild:
                continue
            canal = guild.get_channel(dados["channel_id"])
            if not canal:
                continue
            try:
                msg = await canal.fetch_message(dados["message_id"])
                cfg = get_config(guild_id)
                novo_embed, nova_view = build_painel_embed_view(guild_id, aberto, cfg)
                await msg.edit(embed=novo_embed, view=nova_view)
                status = "ABERTO ✅" if aberto else "FECHADO 🔒"
                print(f"✅ Painel atualizado — {guild.name} — {status}")
            except Exception as e:
                print(f"❌ Erro ao atualizar painel: {e}")


# ─────────────────────────────────────────────
#   VIEW DO PAINEL DE CONFIGURAÇÃO
# ─────────────────────────────────────────────

class ConfigView(discord.ui.View):
    def __init__(self, guild_id, interaction_user):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.interaction_user = interaction_user
        self.add_item(CanalSelect(guild_id, interaction_user))
        self.add_item(CargoSelect(guild_id, interaction_user))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message("❌ Apenas quem criou este painel pode usar!", ephemeral=True)
            return False
        return True

    def build_preview_embed(self):
        cfg = get_config(self.guild_id)
        embed = discord.Embed(description=cfg["mensagem"], color=cfg["cor"])
        if cfg["imagem_grande"]:
            embed.set_image(url=cfg["imagem_grande"])
        if cfg["imagem_pequena"]:
            embed.set_thumbnail(url=cfg["imagem_pequena"])

        canal = f"<#{cfg['canal_id']}>" if cfg["canal_id"] else "❌ Não definido"
        cargo = f"<@&{cfg['cargo_id']}>" if cfg["cargo_id"] else "❌ Não definido"
        cor_hex = f"#{cfg['cor']:06X}"

        embed.add_field(name="📌 Canal:", value=canal, inline=True)
        embed.add_field(name="🎭 Cargo da Staff:", value=cargo, inline=True)
        embed.add_field(name="🎨 Cor:", value=cor_hex, inline=True)
        embed.set_footer(text="Preview do painel de ticket")
        return embed

    @discord.ui.button(label="✏️ Mensagem", style=discord.ButtonStyle.secondary, row=2)
    async def editar_mensagem(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MensagemModal(self.guild_id))

    @discord.ui.button(label="🎨 Cor (opcional)", style=discord.ButtonStyle.secondary, row=2)
    async def editar_cor(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CorModal(self.guild_id))

    @discord.ui.button(label="🖼️ Img. Grande", style=discord.ButtonStyle.secondary, row=2)
    async def imagem_grande(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ImagemModal(self.guild_id, "grande"))

    @discord.ui.button(label="🖼️ Img. Pequena", style=discord.ButtonStyle.secondary, row=2)
    async def imagem_pequena(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ImagemModal(self.guild_id, "pequena"))

    @discord.ui.button(label="💾 Salvar", style=discord.ButtonStyle.success, row=3)
    async def salvar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="✅ **Configurações salvas!**", embed=self.build_preview_embed(), view=self)

    @discord.ui.button(label="🔄 Reset", style=discord.ButtonStyle.danger, row=3)
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_configs[self.guild_id] = DEFAULT_CONFIG.copy()
        view = ConfigView(self.guild_id, interaction.user)
        await interaction.response.edit_message(
            content="🔄 **Resetado!**", embed=view.build_preview_embed(), view=view)

    @discord.ui.button(label="🚀 Enviar", style=discord.ButtonStyle.primary, row=3)
    async def enviar(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_config(self.guild_id)
        if not cfg["canal_id"]:
            await interaction.response.send_message("❌ Selecione um canal!", ephemeral=True)
            return
        if not cfg["cargo_id"]:
            await interaction.response.send_message("❌ Selecione um cargo da staff!", ephemeral=True)
            return

        canal = interaction.guild.get_channel(cfg["canal_id"])
        if not canal:
            await interaction.response.send_message("❌ Canal não encontrado!", ephemeral=True)
            return

        aberto = tickets_abertos_agora()
        embed, view = build_painel_embed_view(self.guild_id, aberto, cfg)
        msg = await canal.send(embed=embed, view=view)

        painel_messages[self.guild_id] = {
            "channel_id": canal.id,
            "message_id": msg.id
        }

        status = "🟢 aberto" if aberto else "🔴 fechado"
        await interaction.response.send_message(
            f"✅ Painel enviado em {canal.mention}! Status: {status}", ephemeral=True)


# ─────────────────────────────────────────────
#   SELECTS
# ─────────────────────────────────────────────

class CanalSelect(discord.ui.ChannelSelect):
    def __init__(self, guild_id, interaction_user):
        super().__init__(
            placeholder="📌 Selecione o canal do ticket...",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1, row=0
        )
        self.guild_id = guild_id
        self.interaction_user = interaction_user

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message("❌ Apenas quem criou pode usar!", ephemeral=True)
            return
        get_config(self.guild_id)["canal_id"] = self.values[0].id
        view = ConfigView(self.guild_id, interaction.user)
        await interaction.response.edit_message(
            content=f"📌 Canal: {self.values[0].mention}",
            embed=view.build_preview_embed(), view=view)


class CargoSelect(discord.ui.RoleSelect):
    def __init__(self, guild_id, interaction_user):
        super().__init__(
            placeholder="🎭 Selecione o cargo da staff...",
            min_values=1, max_values=1, row=1
        )
        self.guild_id = guild_id
        self.interaction_user = interaction_user

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message("❌ Apenas quem criou pode usar!", ephemeral=True)
            return
        get_config(self.guild_id)["cargo_id"] = self.values[0].id
        view = ConfigView(self.guild_id, interaction.user)
        await interaction.response.edit_message(
            content=f"🎭 Cargo: {self.values[0].mention}",
            embed=view.build_preview_embed(), view=view)


# ─────────────────────────────────────────────
#   MODAIS
# ─────────────────────────────────────────────

class MensagemModal(discord.ui.Modal, title="Editar Mensagem"):
    mensagem = discord.ui.TextInput(
        label="Mensagem da Embed",
        style=discord.TextStyle.paragraph,
        placeholder="Digite a mensagem do painel...",
        max_length=1000
    )

    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id
        self.mensagem.default = get_config(guild_id)["mensagem"]

    async def on_submit(self, interaction: discord.Interaction):
        get_config(self.guild_id)["mensagem"] = self.mensagem.value
        view = ConfigView(self.guild_id, interaction.user)
        await interaction.response.edit_message(
            content="📝 Mensagem atualizada!", embed=view.build_preview_embed(), view=view)


class CorModal(discord.ui.Modal, title="Cor da Embed (Opcional)"):
    cor = discord.ui.TextInput(
        label="Cor HEX (vazio = laranja padrão)",
        placeholder="#5865F2",
        required=False, max_length=10
    )

    def __init__(self, guild_id):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_config(self.guild_id)
        texto = self.cor.value.strip()
        if not texto:
            cfg["cor"] = 0xFF8C00
            msg = "🎨 Cor resetada para laranja!"
        else:
            val = cor_hex_valida(texto)
            if val is None:
                await interaction.response.send_message("❌ HEX inválido! Ex: `#FF0000`", ephemeral=True)
                return
            cfg["cor"] = val
            msg = f"🎨 Cor: #{val:06X}"
        view = ConfigView(self.guild_id, interaction.user)
        await interaction.response.edit_message(
            content=msg, embed=view.build_preview_embed(), view=view)


class ImagemModal(discord.ui.Modal, title="Imagem"):
    url = discord.ui.TextInput(
        label="URL da imagem (vazio para remover)",
        placeholder="https://exemplo.com/imagem.png",
        required=False, max_length=500
    )

    def __init__(self, guild_id, tipo):
        super().__init__()
        self.guild_id = guild_id
        self.tipo = tipo

    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_config(self.guild_id)
        val = self.url.value.strip() or None
        if self.tipo == "grande":
            cfg["imagem_grande"] = val
        else:
            cfg["imagem_pequena"] = val
        view = ConfigView(self.guild_id, interaction.user)
        label = "grande" if self.tipo == "grande" else "pequena"
        await interaction.response.edit_message(
            content=f"🖼️ Imagem {label} {'atualizada' if val else 'removida'}!",
            embed=view.build_preview_embed(), view=view)


# ─────────────────────────────────────────────
#   VIEW: ABRIR TICKET
# ─────────────────────────────────────────────

class AbrirTicketView(discord.ui.View):
    def __init__(self, guild_id, aberto=True):
        super().__init__(timeout=None)
        self.guild_id = guild_id

        btn = discord.ui.Button(
            label="🎫 Abrir Ticket" if aberto else "🔒 Tickets Fechados",
            style=discord.ButtonStyle.primary if aberto else discord.ButtonStyle.secondary,
            custom_id="abrir_ticket",
            disabled=not aberto
        )
        btn.callback = self.abrir_ticket_callback
        self.add_item(btn)

    async def abrir_ticket_callback(self, interaction: discord.Interaction):
        if not tickets_abertos_agora():
            ts = proximo_evento_timestamp()
            await interaction.response.send_message(
                f"🔒 Os tickets estão fechados! Abrirão <t:{ts}:R> — <t:{ts}:t>",
                ephemeral=True)
            return

        cfg = get_config(interaction.guild_id)
        guild = interaction.guild
        user = interaction.user

        for ch_id, data in open_tickets.items():
            if data["opener_id"] == user.id and data["guild_id"] == guild.id:
                ch = guild.get_channel(ch_id)
                if ch:
                    await interaction.response.send_message(
                        f"❌ Você já tem um ticket aberto: {ch.mention}", ephemeral=True)
                    return

        cargo = guild.get_role(cfg["cargo_id"]) if cfg["cargo_id"] else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if cargo:
            overwrites[cargo] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True)

        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{user.name}",
            overwrites=overwrites,
            reason=f"Ticket aberto por {user}"
        )

        open_tickets[ticket_channel.id] = {"opener_id": user.id, "guild_id": guild.id}

        embed = discord.Embed(
            title="🎫 Novo Ticket",
            description=f"Olá {user.mention}! Aguarde a staff te atender.\n\n"
                        + (f"{cargo.mention} você foi chamado para atender este ticket." if cargo else ""),
            color=discord.Color.blurple()
        )
        embed.add_field(name="👤 Aberto por:", value=user.mention, inline=True)
        if cargo:
            embed.add_field(name="🎭 Staff:", value=cargo.mention, inline=True)

        ticket_view = TicketControlView(user.id, cfg.get("cargo_id"))
        mention_text = user.mention + (f" | {cargo.mention}" if cargo else "")
        await ticket_channel.send(content=mention_text, embed=embed, view=ticket_view)
        await interaction.response.send_message(
            f"✅ Ticket aberto: {ticket_channel.mention}", ephemeral=True)


# ─────────────────────────────────────────────
#   VIEW: CONTROLE DO TICKET
# ─────────────────────────────────────────────

class TicketControlView(discord.ui.View):
    def __init__(self, opener_id, cargo_id):
        super().__init__(timeout=None)
        self.opener_id = opener_id
        self.cargo_id = cargo_id

    @discord.ui.button(label="❌ Cancelar Ticket", style=discord.ButtonStyle.danger, custom_id="cancelar_ticket")
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opener_id:
            await interaction.response.send_message("❌ Apenas quem abriu pode cancelar!", ephemeral=True)
            return
        await interaction.response.send_message("🔒 Ticket fechando em **5 segundos**...")
        await asyncio.sleep(5)
        open_tickets.pop(interaction.channel.id, None)
        await interaction.channel.delete(reason="Cancelado pelo usuário")

    @discord.ui.button(label="🔒 Fechar Ticket", style=discord.ButtonStyle.secondary, custom_id="fechar_ticket")
    async def fechar(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_roles = [r.id for r in interaction.user.roles]
        if self.cargo_id not in user_roles and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Apenas a staff pode fechar!", ephemeral=True)
            return
        await interaction.response.send_message("🔒 Ticket fechando em **5 segundos**...")
        await asyncio.sleep(5)
        open_tickets.pop(interaction.channel.id, None)
        await interaction.channel.delete(reason="Fechado pela staff")


# ─────────────────────────────────────────────
#   SLASH COMMAND
# ─────────────────────────────────────────────

class TicketGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="ticket", description="Comandos de ticket")

    @app_commands.command(name="create", description="Abre o painel de configuração de ticket")
    @app_commands.checks.has_permissions(administrator=True)
    async def create(self, interaction: discord.Interaction):
        view = ConfigView(interaction.guild_id, interaction.user)
        await interaction.response.send_message(
            content="⚙️ **Painel de Configuração de Ticket**",
            embed=view.build_preview_embed(),
            view=view,
            ephemeral=True
        )

    @create.error
    async def create_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Você precisa ser **Administrador**!", ephemeral=True)


@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    try:
        bot.tree.add_command(TicketGroup())
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} comando(s) sincronizado(s)!")
    except Exception as e:
        print(f"❌ Erro ao sincronizar: {e}")
    verificar_horario.start()


bot.run(TOKEN)
