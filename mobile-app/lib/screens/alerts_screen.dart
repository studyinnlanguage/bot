import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/bot_provider.dart';
import '../core/theme.dart';
import '../models/bot_config.dart';
import '../widgets/common.dart';

class AlertsScreen extends StatefulWidget {
  const AlertsScreen({super.key});

  @override
  State<AlertsScreen> createState() => _AlertsScreenState();
}

class _AlertsScreenState extends State<AlertsScreen> {
  BotConfig? _cfg;
  bool _saving = false;

  BotConfig get cfg {
    _cfg ??= context.read<BotProvider>().config;
    return _cfg!;
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await context.read<BotProvider>().saveConfig(cfg);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('✅ Alert settings saved'),
            backgroundColor: WeexionicTheme.green,
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('❌ $e'), backgroundColor: WeexionicTheme.red),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _testAll() async {
    try {
      final r = await context.read<BotProvider>().testNotifications();
      final msg = r['message'] ?? '';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('${r['success'] == true ? "✅" : "⚠️"} $msg'),
          backgroundColor: r['success'] == true ? WeexionicTheme.green : WeexionicTheme.brandGold,
          duration: const Duration(seconds: 5),
        ),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('❌ $e'), backgroundColor: WeexionicTheme.red),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: WeexionicTheme.bgBase,
      body: SafeArea(
        child: Column(
          children: [
            _buildAppBar(),
            _buildTopBar(),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(14, 12, 14, 20),
                children: [
                  _TelegramCard(cfg: cfg, onChanged: () => setState(() {})),
                  const SizedBox(height: 12),
                  _EmailCard(cfg: cfg, onChanged: () => setState(() {})),
                  const SizedBox(height: 12),
                  _WhatsAppCard(cfg: cfg, onChanged: () => setState(() {})),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      onPressed: _saving ? null : _save,
                      icon: _saving
                          ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                          : const Icon(Icons.save, size: 18),
                      label: Text(_saving ? 'Saving...' : 'SAVE CONFIGURATION', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildAppBar() {
    return Container(
      height: 56,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: const BoxDecoration(
        color: WeexionicTheme.bgSurface,
        border: Border(bottom: BorderSide(color: WeexionicTheme.border)),
      ),
      child: Row(
        children: [
          const Icon(Icons.notifications_active, color: WeexionicTheme.textSecondary, size: 22),
          const SizedBox(width: 12),
          const Expanded(
            child: Text('Alerts & Channels', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
          ),
          IconButton(
            icon: const Icon(Icons.notifications, size: 22),
            onPressed: () {},
          ),
        ],
      ),
    );
  }

  Widget _buildTopBar() {
    int configured = 0;
    if (cfg.telegramEnabled) configured++;
    if (cfg.emailEnabled) configured++;
    if (cfg.whatsappEnabled) configured++;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: const BoxDecoration(
        color: WeexionicTheme.bgSurface,
        border: Border(bottom: BorderSide(color: WeexionicTheme.border)),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('CONFIGURED CHANNELS', style: TextStyle(fontSize: 11, color: WeexionicTheme.textMuted)),
              const SizedBox(height: 2),
              Text(
                '$configured / 3 Active',
                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: WeexionicTheme.brandGold),
              ),
            ],
          ),
          ElevatedButton.icon(
            onPressed: _testAll,
            icon: const Icon(Icons.play_arrow, size: 14),
            label: const Text('Test All', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
            style: ElevatedButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
              minimumSize: Size.zero,
            ),
          ),
        ],
      ),
    );
  }
}

// ============ Telegram Card ============
class _TelegramCard extends StatelessWidget {
  final BotConfig cfg;
  final VoidCallback onChanged;
  const _TelegramCard({required this.cfg, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return _ChannelCard(
      iconBg: const LinearGradient(colors: [Color(0xFF2AABEE), Color(0xFF229ED9)]),
      icon: Icons.send,
      name: 'Telegram Bot',
      desc: 'Instant push notifications',
      enabled: cfg.telegramEnabled,
      onToggle: (v) { cfg.telegramEnabled = v; onChanged(); },
      children: [
        _ChannelInput(
          label: 'Bot Token',
          hint: '7842931845:AAH-7K9...xZq',
          value: cfg.telegramBotToken,
          hintBadge: 'From @BotFather',
          onChanged: (v) { cfg.telegramBotToken = v; onChanged(); },
        ),
        const SizedBox(height: 10),
        _ChannelInput(
          label: 'Chat ID',
          hint: '-100987654321',
          value: cfg.telegramChatId,
          hintBadge: 'From @userinfobot',
          onChanged: (v) { cfg.telegramChatId = v; onChanged(); },
        ),
        const SizedBox(height: 10),
        const _SetupSteps(title: 'Setup Steps', steps: [
          'Open Telegram → Search @BotFather',
          'Send /newbot → Get Bot Token',
          'Add bot to your group/channel',
          'Search @userinfobot → Get Chat ID',
        ]),
        const SizedBox(height: 10),
        _TestButtons(),
      ],
    );
  }
}

// ============ Email Card ============
class _EmailCard extends StatelessWidget {
  final BotConfig cfg;
  final VoidCallback onChanged;
  const _EmailCard({required this.cfg, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return _ChannelCard(
      iconBg: const LinearGradient(colors: [Color(0xFFEA4335), Color(0xFFFBBC04)]),
      icon: Icons.email,
      name: 'Email SMTP',
      desc: 'Direct email alerts',
      enabled: cfg.emailEnabled,
      onToggle: (v) { cfg.emailEnabled = v; onChanged(); },
      children: [
        _ChannelInput(
          label: 'Sender Gmail',
          hint: 'alerts@gmail.com',
          value: cfg.emailSender,
          hintBadge: 'Gmail only',
          onChanged: (v) { cfg.emailSender = v; onChanged(); },
        ),
        const SizedBox(height: 10),
        _ChannelInput(
          label: 'App Password',
          hint: '••••••••••••••••',
          value: cfg.emailPassword,
          obscure: true,
          hintBadge: '16-char',
          onChanged: (v) { cfg.emailPassword = v; onChanged(); },
        ),
        const SizedBox(height: 10),
        _ChannelInput(
          label: 'Recipient Email',
          hint: 'me@gmail.com',
          value: cfg.emailReceiver,
          onChanged: (v) { cfg.emailReceiver = v; onChanged(); },
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: _ChannelInput(
                label: 'SMTP Server',
                hint: 'smtp.gmail.com',
                value: cfg.emailSmtpServer,
                onChanged: (v) { cfg.emailSmtpServer = v; onChanged(); },
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _ChannelInput(
                label: 'Port',
                hint: '587',
                value: cfg.emailSmtpPort.toString(),
                keyboardType: TextInputType.number,
                onChanged: (v) {
                  final p = int.tryParse(v);
                  if (p != null) { cfg.emailSmtpPort = p; onChanged(); }
                },
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        const _SetupSteps(title: 'Setup Steps', steps: [
          'Google Account → Security → 2-Step Verification',
          'Generate App Password (16-char)',
          'Use Gmail address + this password',
          'Default SMTP: smtp.gmail.com:587',
        ]),
        const SizedBox(height: 10),
        _TestButtons(),
      ],
    );
  }
}

// ============ WhatsApp Card ============
class _WhatsAppCard extends StatelessWidget {
  final BotConfig cfg;
  final VoidCallback onChanged;
  const _WhatsAppCard({required this.cfg, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return _ChannelCard(
      iconBg: const LinearGradient(colors: [Color(0xFF25D366), Color(0xFF128C7E)]),
      icon: Icons.chat,
      name: 'WhatsApp',
      desc: 'CallMeBot API alerts',
      enabled: cfg.whatsappEnabled,
      onToggle: (v) { cfg.whatsappEnabled = v; onChanged(); },
      children: [
        _ChannelInput(
          label: 'Phone Number',
          hint: '+923001234567',
          value: cfg.whatsappPhone,
          hintBadge: 'With country code',
          onChanged: (v) { cfg.whatsappPhone = v; onChanged(); },
        ),
        const SizedBox(height: 10),
        _ChannelInput(
          label: 'API Key',
          hint: '••••••••••',
          value: cfg.whatsappApikey,
          obscure: true,
          hintBadge: 'From CallMeBot',
          onChanged: (v) { cfg.whatsappApikey = v; onChanged(); },
        ),
        const SizedBox(height: 10),
        const _SetupSteps(title: 'Setup Steps', steps: [
          'Add +34 613 75 96 94 to WhatsApp contacts',
          'Send: "I allow callmebot to send me messages"',
          'Receive API Key in response',
          'Paste key + your phone number above',
        ]),
        const SizedBox(height: 10),
        _TestButtons(),
      ],
    );
  }
}

// ============ Shared widgets ============
class _ChannelCard extends StatelessWidget {
  final Gradient iconBg;
  final IconData icon;
  final String name;
  final String desc;
  final bool enabled;
  final ValueChanged<bool> onToggle;
  final List<Widget> children;
  const _ChannelCard({
    required this.iconBg,
    required this.icon,
    required this.name,
    required this.desc,
    required this.enabled,
    required this.onToggle,
    required this.children,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: WeexionicTheme.bgSurface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: WeexionicTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 36, height: 36,
                decoration: BoxDecoration(gradient: iconBg, borderRadius: BorderRadius.circular(10)),
                child: Icon(icon, color: Colors.white, size: 20),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(name, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                    Text(desc, style: const TextStyle(fontSize: 10, color: WeexionicTheme.textMuted)),
                  ],
                ),
              ),
              Switch(
                value: enabled,
                onChanged: onToggle,
                activeColor: WeexionicTheme.brandGold,
              ),
            ],
          ),
          const Divider(height: 16),
          ...children,
        ],
      ),
    );
  }
}

class _ChannelInput extends StatelessWidget {
  final String label;
  final String hint;
  final String value;
  final String? hintBadge;
  final bool obscure;
  final TextInputType? keyboardType;
  final ValueChanged<String> onChanged;
  const _ChannelInput({
    required this.label,
    required this.hint,
    required this.value,
    this.hintBadge,
    this.obscure = false,
    this.keyboardType,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: const TextStyle(fontSize: 11, color: WeexionicTheme.textMuted, fontWeight: FontWeight.w500)),
            if (hintBadge != null)
              Text(hintBadge!, style: const TextStyle(fontSize: 9, color: WeexionicTheme.brandGold, fontWeight: FontWeight.w600)),
          ],
        ),
        const SizedBox(height: 6),
        TextFormField(
          initialValue: value,
          obscureText: obscure,
          keyboardType: keyboardType,
          style: const TextStyle(fontSize: 12, fontFamily: 'RobotoMono', color: WeexionicTheme.textPrimary),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: const TextStyle(color: WeexionicTheme.textFaint),
            suffixIcon: obscure
                ? const Icon(Icons.visibility_off, size: 14, color: WeexionicTheme.textMuted)
                : (keyboardType == TextInputType.number
                    ? const Icon(Icons.phone, size: 14, color: WeexionicTheme.textMuted)
                    : const Icon(Icons.visibility, size: 14, color: WeexionicTheme.textMuted)),
          ),
          onChanged: onChanged,
        ),
      ],
    );
  }
}

class _SetupSteps extends StatelessWidget {
  final String title;
  final List<String> steps;
  const _SetupSteps({required this.title, required this.steps});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: WeexionicTheme.bgElevated,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: WeexionicTheme.borderLight, width: 1, style: BorderStyle.solid),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.list, size: 12, color: WeexionicTheme.brandGold),
              const SizedBox(width: 4),
              Text(
                title.toUpperCase(),
                style: const TextStyle(fontSize: 10, color: WeexionicTheme.brandGold, fontWeight: FontWeight.w700, letterSpacing: 0.5),
              ),
            ],
          ),
          const SizedBox(height: 6),
          ...steps.asMap().entries.map((e) => Padding(
            padding: const EdgeInsets.only(bottom: 2, left: 16),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${e.key + 1}. ', style: const TextStyle(fontSize: 10.5, color: WeexionicTheme.textMuted, fontFamily: 'RobotoMono')),
                Expanded(
                  child: Text(
                    e.value,
                    style: const TextStyle(fontSize: 10.5, color: WeexionicTheme.textSecondary, height: 1.5),
                  ),
                ),
              ],
            ),
          )),
        ],
      ),
    );
  }
}

class _TestButtons extends StatelessWidget {
  const _TestButtons();

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: OutlinedButton.icon(
            onPressed: () async {
              try {
                final r = await context.read<BotProvider>().testNotifications();
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(r['success'] == true ? '✅ Test sent' : '⚠️ ${r["message"] ?? "Failed"}'),
                    backgroundColor: r['success'] == true ? WeexionicTheme.green : WeexionicTheme.brandGold,
                  ),
                );
              } catch (e) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('❌ $e'), backgroundColor: WeexionicTheme.red),
                );
              }
            },
            icon: const Icon(Icons.play_arrow, size: 14),
            label: const Text('Send Test', style: TextStyle(fontSize: 11)),
            style: OutlinedButton.styleFrom(
              foregroundColor: WeexionicTheme.textSecondary,
              side: const BorderSide(color: WeexionicTheme.borderLight),
              padding: const EdgeInsets.symmetric(vertical: 9),
            ),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 9),
            decoration: BoxDecoration(
              color: WeexionicTheme.green.withOpacity(0.15),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: WeexionicTheme.green.withOpacity(0.3)),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: const [
                Icon(Icons.check_circle, size: 14, color: WeexionicTheme.green),
                SizedBox(width: 4),
                Text('Connected', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: WeexionicTheme.green)),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
