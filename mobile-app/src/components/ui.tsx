// Shared premium UI components — gold-dark design system.
import React from 'react';
import {
  ActivityIndicator,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  StyleSheet,
  TextStyle,
  ViewStyle,
} from 'react-native';
import { C, S } from '../theme/theme';

export function Card({ children, style }: { children: React.ReactNode; style?: ViewStyle | ViewStyle[] }) {
  return <View style={[S.card, style]}>{children}</View>;
}

export function Lbl({ children, style }: { children: React.ReactNode; style?: TextStyle }) {
  return <Text style={[S.lbl, style]}>{children}</Text>;
}

export function GoldButton({
  title,
  onPress,
  loading,
  disabled,
  style,
}: {
  title: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
}) {
  return (
    <TouchableOpacity
      activeOpacity={0.85}
      onPress={onPress}
      disabled={disabled || loading}
      style={[
        {
          backgroundColor: disabled || loading ? C.goldD : C.gold,
          borderRadius: 14,
          paddingVertical: 14,
          alignItems: 'center',
          justifyContent: 'center',
        },
        style,
      ]}>
      {loading ? (
        <ActivityIndicator color={C.bg} />
      ) : (
        <Text style={{ color: C.bg, fontWeight: '800', fontSize: 14, letterSpacing: 1.2 }}>
          {title}
        </Text>
      )}
    </TouchableOpacity>
  );
}

export function GlassButton({
  title,
  onPress,
  danger,
  style,
}: {
  title: string;
  onPress: () => void;
  danger?: boolean;
  style?: ViewStyle;
}) {
  return (
    <TouchableOpacity
      activeOpacity={0.85}
      onPress={onPress}
      style={[
        {
          borderRadius: 14,
          paddingVertical: 13,
          alignItems: 'center',
          borderWidth: 1,
          borderColor: danger ? 'rgba(234,57,67,0.45)' : 'rgba(212,175,55,0.35)',
          backgroundColor: danger ? 'rgba(234,57,67,0.08)' : 'rgba(212,175,55,0.06)',
        },
        style,
      ]}>
      <Text style={{ color: danger ? C.loss : C.goldB, fontWeight: '700', fontSize: 13, letterSpacing: 0.6 }}>
        {title}
      </Text>
    </TouchableOpacity>
  );
}

export function Field({
  label,
  value,
  onChangeText,
  placeholder,
  secure,
  keyboardType,
  hint,
  editable = true,
  autoCapitalize = 'none',
}: {
  label: string;
  value: string;
  onChangeText: (t: string) => void;
  placeholder?: string;
  secure?: boolean;
  keyboardType?: any;
  hint?: string;
  editable?: boolean;
  autoCapitalize?: 'none' | 'sentences' | 'words' | 'characters';
}) {
  return (
    <View style={{ marginBottom: 12 }}>
      <Lbl style={{ marginBottom: 6 }}>{label}</Lbl>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={C.dim2}
        secureTextEntry={secure}
        keyboardType={keyboardType}
        editable={editable}
        autoCapitalize={autoCapitalize}
        autoCorrect={false}
        style={{
          backgroundColor: 'rgba(0,0,0,0.35)',
          borderColor: 'rgba(212,175,55,0.25)',
          borderWidth: 1,
          borderRadius: 12,
          color: C.txt,
          paddingHorizontal: 12,
          paddingVertical: 11,
          fontSize: 14,
        }}
      />
      {hint ? (
        <Text style={{ color: C.dim2, fontSize: 11, marginTop: 4 }}>{hint}</Text>
      ) : null}
    </View>
  );
}

export function StatusPill({ running, testnet, exchange }: { running: boolean; testnet: boolean; exchange: string }) {
  const color = running ? C.profit : C.dim2;
  const label = running ? 'RUNNING' : 'STOPPED';
  return (
    <View style={[S.row, { gap: 6 }] as any}>
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: 6,
          borderColor: 'rgba(212,175,55,0.25)',
          borderWidth: 1,
          borderRadius: 999,
          paddingHorizontal: 10,
          paddingVertical: 5,
          backgroundColor: 'rgba(0,0,0,0.3)',
        } as any}>
        <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: color }} />
        <Text style={{ color: C.txt, fontSize: 11, fontWeight: '800', letterSpacing: 1 }}>{label}</Text>
      </View>
      <View
        style={{
          borderColor: 'rgba(212,175,55,0.25)',
          borderWidth: 1,
          borderRadius: 999,
          paddingHorizontal: 10,
          paddingVertical: 5,
          backgroundColor: 'rgba(0,0,0,0.3)',
        } as any}>
        <Text style={{ color: testnet ? C.orange : C.goldB, fontSize: 11, fontWeight: '800', letterSpacing: 0.6 }}>
          {exchange?.toUpperCase()}{testnet ? ' · TESTNET' : ' · LIVE'}
        </Text>
      </View>
    </View>
  );
}

export function Chip({
  label,
  active,
  onPress,
  small,
}: {
  label: string;
  active?: boolean;
  onPress?: () => void;
  small?: boolean;
}) {
  return (
    <TouchableOpacity
      onPress={onPress}
      activeOpacity={0.8}
      style={{
        paddingHorizontal: small ? 10 : 14,
        paddingVertical: small ? 6 : 8,
        borderRadius: 999,
        borderWidth: 1,
        borderColor: active ? C.gold : 'rgba(212,175,55,0.22)',
        backgroundColor: active ? 'rgba(212,175,55,0.16)' : 'rgba(0,0,0,0.25)',
        marginRight: 8,
        marginBottom: 8,
      } as any}>
      <Text style={{ color: active ? C.goldB : C.dim, fontWeight: active ? '800' : '600', fontSize: small ? 11 : 12.5 }}>
        {label}
      </Text>
    </TouchableOpacity>
  );
}

export function KV({ k, v, color }: { k: string; v: React.ReactNode; color?: string }) {
  return (
    <View style={{ marginBottom: 10 }}>
      <Lbl>{k}</Lbl>
      <Text style={{ color: color || C.txt, fontSize: 15, fontWeight: '700', marginTop: 2 }}>{v}</Text>
    </View>
  );
}

export function ErrorNote({ msg }: { msg: string | null }) {
  if (!msg) return null;
  return (
    <View style={{ backgroundColor: 'rgba(234,57,67,0.10)', borderColor: 'rgba(234,57,67,0.4)', borderWidth: 1, borderRadius: 10, padding: 10, marginBottom: 10 }}>
      <Text style={{ color: C.loss, fontSize: 12.5 }}>{msg}</Text>
    </View>
  );
}

export function OkNote({ msg }: { msg: string | null }) {
  if (!msg) return null;
  return (
    <View style={{ backgroundColor: 'rgba(22,199,132,0.10)', borderColor: 'rgba(22,199,132,0.4)', borderWidth: 1, borderRadius: 10, padding: 10, marginBottom: 10 }}>
      <Text style={{ color: C.profit, fontSize: 12.5 }}>{msg}</Text>
    </View>
  );
}

export function SectionTitle({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <View style={[S.between, { marginBottom: 10 }] as any}>
      <Text style={{ color: C.gold, fontWeight: '800', fontSize: 12.5, letterSpacing: 2 }}>{children}</Text>
      {right}
    </View>
  );
}

export function Empty({ text }: { text: string }) {
  return (
    <View style={{ alignItems: 'center', paddingVertical: 26 }}>
      <Text style={{ color: C.dim2, fontSize: 13 }}>{text}</Text>
    </View>
  );
}

export function Logo({ size = 46 }: { size?: number }) {
  // "Ascend W" monogram drawn natively (no image asset needed)
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: size * 0.28,
        backgroundColor: '#141210',
        borderWidth: 1.2,
        borderColor: 'rgba(212,175,55,0.55)',
        alignItems: 'center',
        justifyContent: 'center',
        shadowColor: C.gold,
        shadowOpacity: 0.35,
        shadowRadius: 12,
        elevation: 6,
      } as any}>
      <Text style={{ color: C.gold, fontSize: size * 0.5, fontWeight: '900', fontStyle: 'italic' }}>W</Text>
      <View style={{ position: 'absolute', top: size * 0.13, right: size * 0.16, width: 0, height: 0, borderLeftWidth: 4, borderBottomWidth: 6, borderLeftColor: 'transparent', borderBottomColor: C.goldB, transform: [{ rotate: '45deg' }] }} />
    </View>
  );
}
