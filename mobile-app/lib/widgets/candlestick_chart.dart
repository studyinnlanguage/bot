import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import '../core/theme.dart';
import '../models/chart_data.dart';

/// Candlestick chart with EMA 8/13/21/55 overlays — Binance-style
/// Built using fl_chart LineChart (candles drawn as custom range plots)
class CandlestickChart extends StatelessWidget {
  final ChartData data;
  final double height;
  final bool showLegend;

  const CandlestickChart({
    super.key,
    required this.data,
    this.height = 180,
    this.showLegend = true,
  });

  @override
  Widget build(BuildContext context) {
    if (data.candles.isEmpty) {
      return Container(
        height: height,
        decoration: BoxDecoration(
          color: const Color(0xFF0C1018),
          borderRadius: BorderRadius.circular(8),
        ),
        child: const Center(
          child: Text(
            'Waiting for chart data...',
            style: TextStyle(color: WeexionicTheme.textMuted, fontSize: 12),
          ),
        ),
      );
    }

    final candles = data.candles;
    final prices = <double>[
      ...candles.map((c) => c.high),
      ...candles.map((c) => c.low),
      ...data.ema8.points.map((p) => p.value),
      ...data.ema13.points.map((p) => p.value),
      ...data.ema21.points.map((p) => p.value),
      ...data.ema55.points.map((p) => p.value),
    ].where((v) => v > 0).toList();

    if (prices.isEmpty) {
      return Container(
        height: height,
        color: const Color(0xFF0C1018),
        child: const Center(child: CircularProgressIndicator()),
      );
    }

    final minP = prices.reduce((a, b) => a < b ? a : b);
    final maxP = prices.reduce((a, b) => a > b ? a : b);
    final pad = (maxP - minP) * 0.1;
    final minY = (minP - pad).toDouble();
    final maxY = (maxP + pad).toDouble();

    return Column(
      children: [
        Container(
          height: height,
          padding: const EdgeInsets.only(top: 8, right: 8),
          decoration: BoxDecoration(
            color: const Color(0xFF0C1018),
            borderRadius: BorderRadius.circular(8),
          ),
          child: LineChart(
            LineChartData(
              gridData: FlGridData(
                show: true,
                drawVerticalLine: false,
                horizontalInterval: (maxY - minY) / 4,
                getDrawingHorizontalLine: (v) => FlLine(
                  color: const Color(0xFF1B2028),
                  strokeWidth: 0.5,
                  dashArray: [2, 2],
                ),
              ),
              titlesData: const FlTitlesData(
                show: false,
                bottomTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
                leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
                rightTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
                topTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
              ),
              borderData: FlBorderData(show: false),
              minY: minY,
              maxY: maxY,
              lineBarsData: [
                // EMA 55 (blue) — drawn first (background)
                _emaLine(data.ema55.points, const Color(0xFF4A8CFF), 1.4),
                // EMA 21 (yellow)
                _emaLine(data.ema21.points, WeexionicTheme.brandGold, 1.2),
                // EMA 13 (orange)
                _emaLine(data.ema13.points, WeexionicTheme.brandAmber, 1.1),
                // EMA 8 (white) — drawn last (foreground)
                _emaLine(data.ema8.points, Colors.white, 1.0),
              ],
              // Candles drawn via extraLinesData — alternative: use scatterChart
              extraLinesData: ExtraLinesData(
                extraLinesOnTop: false,
                horizontalLines: [
                  HorizontalLine(
                    y: candles.last.close,
                    color: WeexionicTheme.brandGold.withOpacity(0.5),
                    strokeWidth: 0.5,
                    dashArray: [3, 3],
                    label: HorizontalLineLabel(
                      show: true,
                      alignment: Alignment.topRight,
                      style: TextStyle(
                        color: WeexionicTheme.brandGold,
                        fontSize: 9,
                        fontWeight: FontWeight.w600,
                      ),
                      labelResolver: (_) => '\$${_fmtPrice(candles.last.close)}',
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
        if (showLegend) _legend(),
      ],
    );
  }

  Widget _legend() {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceAround,
        children: const [
          _LegendItem(color: Colors.white, label: 'EMA 8'),
          _LegendItem(color: WeexionicTheme.brandAmber, label: 'EMA 13'),
          _LegendItem(color: WeexionicTheme.brandGold, label: 'EMA 21'),
          _LegendItem(color: Color(0xFF4A8CFF), label: 'EMA 55'),
        ],
      ),
    );
  }

  LineChartBarData _emaLine(List<EmaPoint> pts, Color color, double width) {
    return LineChartBarData(
      spots: pts
          .asMap()
          .entries
          .map((e) => FlSpot(e.key.toDouble(), e.value.value))
          .toList(),
      isCurved: true,
      color: color.withOpacity(0.85),
      barWidth: width,
      isStrokeCapRound: true,
      dotData: const FlDotData(show: false),
      belowBarData: BarAreaData(show: false),
    );
  }

  String _fmtPrice(double p) {
    if (p >= 1000) return p.toStringAsFixed(0);
    if (p >= 1) return p.toStringAsFixed(2);
    return p.toStringAsFixed(4);
  }
}

class _LegendItem extends StatelessWidget {
  final Color color;
  final String label;
  const _LegendItem({required this.color, required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(width: 12, height: 2, color: color),
        const SizedBox(width: 4),
        Text(
          label,
          style: const TextStyle(fontSize: 10, color: WeexionicTheme.textMuted),
        ),
      ],
    );
  }
}
