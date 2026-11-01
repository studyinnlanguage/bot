import React, { useEffect } from 'react';
import { View, Text, ActivityIndicator } from 'react-native';
import { Logo } from '../components/ui';
import { C } from '../theme/theme';
import { useAuth } from '../store/auth';

export function SplashScreen({ navigation }: any) {
  const { loading, user } = useAuth();

  useEffect(() => {
    if (!loading) {
      navigation.replace(user ? 'Main' : 'Auth');
    }
  }, [loading, user, navigation]);

  return (
    <View style={{ flex: 1, backgroundColor: C.bg2, alignItems: 'center', justifyContent: 'center' }}>
      <Logo size={92} />
      <Text style={{ color: C.gold, fontSize: 30, fontWeight: '900', letterSpacing: 8, marginTop: 18 }}>
        WEEXIONIC
      </Text>
      <Text style={{ color: C.dim, fontSize: 11, letterSpacing: 4, marginTop: 6 }}>
        QUAD-TREND QUANTITATIVE ENGINE
      </Text>
      <ActivityIndicator color={C.gold} style={{ marginTop: 34 }} />
    </View>
  );
}
