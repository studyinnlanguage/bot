/// Bot configuration — matches GET /api/config response
/// Source: bot-engine/app.py GET /api/config (~line 320-380)
class BotConfig {
  String apiKey;
  String apiSecret;
  String apiPassphrase;          // WEEX only
  String exchange;               // 'binance' | 'weex' | 'primexbt'
  bool testnet;
  String symbol;                 // primary symbol
  List<String> symbolsList;      // up to 3
  String timeframe;              // 1m,3m,5m,15m,30m,1h,2h,4h,1d,1w
  int leverage;
  String amountMode;             // 'fixed' | 'percent'
  double amount;                 // USDT when fixed
  double amountPct;              // % when percent
  double stopLossPct;
  double takeProfitPct;          // server-forced = stopLossPct
  double trailingRoePct;         // server-forced = 100
  String tpMode;                 // 'fixed' | 'trailing' | 'ema_reversal'
  String mode;                   // 'both' | 'long' | 'short'
  bool autoStart;
  int maxConcurrentTrades;       // 1-3

  // Telegram
  bool telegramEnabled;
  String telegramBotToken;
  String telegramChatId;

  // Email
  bool emailEnabled;
  String emailSmtpServer;
  int emailSmtpPort;
  String emailSender;
  String emailPassword;
  String emailReceiver;

  // WhatsApp
  bool whatsappEnabled;
  String whatsappPhone;
  String whatsappApikey;

  BotConfig({
    this.apiKey = '',
    this.apiSecret = '',
    this.apiPassphrase = '',
    this.exchange = 'binance',
    this.testnet = true,
    this.symbol = 'BTCUSDT',
    this.symbolsList = const ['BTCUSDT'],
    this.timeframe = '5m',
    this.leverage = 50,
    this.amountMode = 'percent',
    this.amount = 100,
    this.amountPct = 10,
    this.stopLossPct = 2,
    this.takeProfitPct = 2,
    this.trailingRoePct = 100,
    this.tpMode = 'fixed',
    this.mode = 'both',
    this.autoStart = false,
    this.maxConcurrentTrades = 1,
    this.telegramEnabled = false,
    this.telegramBotToken = '',
    this.telegramChatId = '',
    this.emailEnabled = false,
    this.emailSmtpServer = 'smtp.gmail.com',
    this.emailSmtpPort = 587,
    this.emailSender = '',
    this.emailPassword = '',
    this.emailReceiver = '',
    this.whatsappEnabled = false,
    this.whatsappPhone = '',
    this.whatsappApikey = '',
  });

  factory BotConfig.fromJson(Map<String, dynamic> j) => BotConfig(
    apiKey: (j['api_key'] ?? '').toString(),
    apiSecret: (j['api_secret'] ?? '').toString(),
    apiPassphrase: (j['api_passphrase'] ?? '').toString(),
    exchange: (j['exchange'] ?? 'binance').toString(),
    testnet: j['testnet'] ?? true,
    symbol: (j['symbol'] ?? 'BTCUSDT').toString(),
    symbolsList: (j['symbols_list'] as List?)?.map((e) => e.toString()).toList() ?? ['BTCUSDT'],
    timeframe: (j['timeframe'] ?? '5m').toString(),
    leverage: (j['leverage'] ?? 50).toInt(),
    amountMode: (j['amount_mode'] ?? 'percent').toString(),
    amount: _d(j['amount'], fallback: 100),
    amountPct: _d(j['amount_pct'], fallback: 10),
    stopLossPct: _d(j['stop_loss_pct'], fallback: 2),
    takeProfitPct: _d(j['take_profit_pct'], fallback: 2),
    trailingRoePct: _d(j['trailing_roe_pct'], fallback: 100),
    tpMode: (j['tp_mode'] ?? 'fixed').toString(),
    mode: (j['mode'] ?? 'both').toString(),
    autoStart: j['auto_start'] ?? false,
    maxConcurrentTrades: (j['max_concurrent_trades'] ?? 1).toInt(),
    telegramEnabled: j['telegram_enabled'] ?? false,
    telegramBotToken: (j['telegram_bot_token'] ?? '').toString(),
    telegramChatId: (j['telegram_chat_id'] ?? '').toString(),
    emailEnabled: j['email_enabled'] ?? false,
    emailSmtpServer: (j['email_smtp_server'] ?? 'smtp.gmail.com').toString(),
    emailSmtpPort: (j['email_smtp_port'] ?? 587).toInt(),
    emailSender: (j['email_sender'] ?? '').toString(),
    emailPassword: (j['email_password'] ?? '').toString(),
    emailReceiver: (j['email_receiver'] ?? '').toString(),
    whatsappEnabled: j['whatsapp_enabled'] ?? false,
    whatsappPhone: (j['whatsapp_phone'] ?? '').toString(),
    whatsappApikey: (j['whatsapp_apikey'] ?? '').toString(),
  );

  static double _d(dynamic v, {double fallback = 0}) {
    if (v == null) return fallback;
    if (v is num) return v.toDouble();
    return double.tryParse(v.toString()) ?? fallback;
  }

  /// Serialise for POST /api/config — server strips secrets on return
  Map<String, dynamic> toJson() => {
    if (apiKey.isNotEmpty) 'api_key': apiKey,
    if (apiSecret.isNotEmpty) 'api_secret': apiSecret,
    if (apiPassphrase.isNotEmpty) 'api_passphrase': apiPassphrase,
    'exchange': exchange,
    'testnet': testnet,
    'symbol': symbol,
    'symbols_list': symbolsList,
    'timeframe': timeframe,
    'leverage': leverage,
    'amount_mode': amountMode,
    'amount': amount,
    'amount_pct': amountPct,
    'stop_loss_pct': stopLossPct,
    'take_profit_pct': takeProfitPct,
    'tp_mode': tpMode,
    'mode': mode,
    'auto_start': autoStart,
    'max_concurrent_trades': maxConcurrentTrades,
    'telegram_enabled': telegramEnabled,
    if (telegramBotToken.isNotEmpty) 'telegram_bot_token': telegramBotToken,
    'telegram_chat_id': telegramChatId,
    'email_enabled': emailEnabled,
    'email_smtp_server': emailSmtpServer,
    'email_smtp_port': emailSmtpPort,
    'email_sender': emailSender,
    if (emailPassword.isNotEmpty) 'email_password': emailPassword,
    'email_receiver': emailReceiver,
    'whatsapp_enabled': whatsappEnabled,
    'whatsapp_phone': whatsappPhone,
    if (whatsappApikey.isNotEmpty) 'whatsapp_apikey': whatsappApikey,
  };

  BotConfig copyWith() => BotConfig.fromJson(toJson());
}
