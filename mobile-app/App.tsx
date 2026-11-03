// WEEXIONIC native app — navigation shell.
// Bottom tabs: Cockpit / Vault / Ledger / Engine / Account (+ Radar & Pulse screens).
import React from 'react';
import { Text, View } from 'react-native';
import { NavigationContainer, DefaultTheme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { AuthProvider, useAuth } from './src/store/auth';
import { SplashScreen } from './src/screens/SplashScreen';
import { LoginScreen } from './src/screens/LoginScreen';
import { CockpitScreen } from './src/screens/CockpitScreen';
import { VaultScreen } from './src/screens/VaultScreen';
import { LedgerScreen } from './src/screens/LedgerScreen';
import { EngineScreen } from './src/screens/EngineScreen';
import { RadarScreen } from './src/screens/RadarScreen';
import { PulseScreen } from './src/screens/PulseScreen';
import { AccountScreen } from './src/screens/AccountScreen';
import { C } from './src/theme/theme';

const Stack = createNativeStackNavigator();
const Tabs = createBottomTabNavigator();

const navTheme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    background: C.bg,
    card: '#0b0b0d',
    text: C.txt,
    border: 'rgba(255,45,60, 0.18)',
    primary: C.neon,
  },
};

function TabIcon({ glyph, focused }: { glyph: string; focused: boolean }) {
  return (
    <View style={{ alignItems: 'center' }}>
      <Text style={{ color: focused ? C.neon : C.dim2, fontSize: 19, lineHeight: 22 }}>{glyph}</Text>
      <View style={{ width: 4, height: 4, borderRadius: 2, marginTop: 3, backgroundColor: focused ? C.neon : 'transparent' }} />
    </View>
  );
}

function MainTabs() {
  return (
    <Tabs.Navigator
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: C.neon,
        tabBarInactiveTintColor: C.dim2,
        tabBarStyle: {
          backgroundColor: '#0b0b0d',
          borderTopColor: 'rgba(255,45,60, 0.20)',
          borderTopWidth: 1,
          height: 84,
          paddingTop: 10,
          paddingBottom: 18,
        },
        tabBarLabelStyle: { fontSize: 9.5, fontWeight: '700', letterSpacing: 0.6 },
      }}>
      <Tabs.Screen name="Cockpit" component={CockpitScreen} options={{ tabBarIcon: ({ focused }) => <TabIcon glyph="◉" focused={focused} /> }} />
      <Tabs.Screen name="Vault" component={VaultScreen} options={{ tabBarIcon: ({ focused }) => <TabIcon glyph="▣" focused={focused} /> }} />
      <Tabs.Screen name="Ledger" component={LedgerScreen} options={{ tabBarIcon: ({ focused }) => <TabIcon glyph="≡" focused={focused} /> }} />
      <Tabs.Screen name="Engine" component={EngineScreen} options={{ tabBarIcon: ({ focused }) => <TabIcon glyph="⚙" focused={focused} /> }} />
      <Tabs.Screen name="Account" component={AccountScreen} options={{ tabBarIcon: ({ focused }) => <TabIcon glyph="⬤" focused={focused} /> }} />
    </Tabs.Navigator>
  );
}

function Root() {
  const { loading, user } = useAuth();
  if (loading) return <SplashScreen navigation={{ replace: () => {} }} />;
  return (
    <Stack.Navigator screenOptions={{ headerShown: false, animation: 'fade' }}>
      {user ? (
        <>
          <Stack.Screen name="Main" component={MainTabs} />
          <Stack.Screen name="Radar" component={RadarScreen} />
          <Stack.Screen name="Pulse" component={PulseScreen} />
        </>
      ) : (
        <Stack.Screen name="Auth" component={LoginScreen} />
      )}
    </Stack.Navigator>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <NavigationContainer theme={navTheme}>
        <Stack.Navigator screenOptions={{ headerShown: false }}>
          <Stack.Screen name="Splash" component={SplashWrapper} />
          <Stack.Screen name="Root" component={Root} />
        </Stack.Navigator>
      </NavigationContainer>
    </AuthProvider>
  );
}

function SplashWrapper({ navigation }: any) {
  const { loading, user } = useAuth();
  React.useEffect(() => {
    if (!loading) {
      navigation.replace('Root');
    }
  }, [loading, navigation]);
  return <SplashScreen navigation={{ replace: () => {} }} />;
}
