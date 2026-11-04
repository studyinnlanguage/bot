/**
 * @format
 */
import 'react-native';
import React from 'react';
import { it, jest, expect } from '@jest/globals';
import renderer from 'react-test-renderer';

// Socket layer: never open real connections inside Jest.
jest.mock('../src/socket/ws', () => ({
  getSocket: jest.fn(async () => ({
    on: jest.fn(),
    off: jest.fn(),
    removeAllListeners: jest.fn(),
    disconnect: jest.fn(),
    connected: false,
  })),
  closeSocket: jest.fn(),
}));

// Deep-link listener would keep async work alive past teardown.
import { Linking } from 'react-native';
Object.defineProperty(Linking, 'addEventListener', {
  configurable: true,
  value: jest.fn(() => ({ remove: jest.fn() })),
});
Object.defineProperty(Linking, 'getInitialURL', {
  configurable: true,
  value: jest.fn(async () => null),
});
Object.defineProperty(Linking, 'openURL', {
  configurable: true,
  value: jest.fn(async () => {}),
});

// Note: test renderer must be required after react-native.
const ReactTestRenderer = require('react-test-renderer');
import App from '../App';

it('renders correctly (splash → auth shell)', async () => {
  let tree: renderer.ReactTestRenderer | undefined;
  await ReactTestRenderer.act(async () => {
    tree = ReactTestRenderer.create(<App />);
  });
  expect(tree && tree.toJSON()).toBeTruthy();
});
