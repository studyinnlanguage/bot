// Jest environment setup — mock native modules that have no JS fallback.
const mock = require('@react-native-async-storage/async-storage/jest/async-storage-mock');
jest.mock('@react-native-async-storage/async-storage', () => mock);
