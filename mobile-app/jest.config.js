module.exports = {
  preset: 'react-native',
  // AsyncStorage native module mock (official integration).
  setupFiles: ['./jest.setup.js'],
  // RN preset does not transpile ESM-only deps — transform everything we ship.
  transformIgnorePatterns: [
    'node_modules/(?!(react-native|@react-native|@react-navigation|react-native-svg|react-native-qrcode-svg|react-native-screens|react-native-safe-area-context|@react-native-async-storage|socket.io-client|engine.io-client)/)',
  ],
};
