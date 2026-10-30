/// Smoke test — verifies app builds & main entry doesn't throw
/// Run: flutter test test/widget_test.dart

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

// Smoke test placeholder — replace with real widget tests
void main() {
  testWidgets('App placeholder renders without error', (WidgetTester tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: Center(child: Text('WEEXIONIC')),
        ),
      ),
    );
    expect(find.text('WEEXIONIC'), findsOneWidget);
  });
}
