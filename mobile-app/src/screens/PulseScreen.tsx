// Pulse — live engine activity log via Socket.IO.
import React, { useEffect, useRef, useState } from 'react';
import { FlatList, ScrollView, Text, View } from 'react-native';
import { Card, Empty, GlassButton, SectionTitle } from '../components/ui';
import { getSocket } from '../socket/ws';
import { C } from '../theme/theme';

interface LogLine {
  id: number;
  level: string;
  msg: string;
  ts: string;
}

let seq = 0;

export function PulseScreen() {
  const [lines, setLines] = useState<LogLine[]>([]);
  const listRef = useRef<FlatList<LogLine>>(null);

  useEffect(() => {
    let alive = true;
    const bind = async () => {
      const sock = await getSocket();
      if (!alive) return;
      const onLog = (d: any) => {
        setLines(prev => {
          const next = [
            ...prev,
            { id: seq++, level: d?.level || 'info', msg: String(d?.msg ?? ''), ts: new Date().toLocaleTimeString() },
          ];
          return next.slice(-300);
        });
      };
      sock.on('log', onLog);
      return () => sock.off('log', onLog);
    };
    const cleanup = bind();
    return () => {
      alive = false;
      Promise.resolve(cleanup).then(fn => fn && fn());
    };
  }, []);

  const colorFor = (lvl: string) =>
    lvl === 'error' ? C.loss : lvl === 'warn' ? C.orange : lvl === 'success' ? C.profit : C.dim;

  return (
    <View style={{ flex: 1, backgroundColor: C.bg, padding: 14, paddingTop: 16 }}>
      <SectionTitle right={<Text style={{ color: C.dim2, fontSize: 10.5 }}>LIVE · SOCKET.IO</Text>}>
        PULSE · ENGINE ACTIVITY
      </SectionTitle>
      <Card style={{ flex: 1, padding: 8 }}>
        {lines.length === 0 ? (
          <Empty text="Listening… engine events will appear here in real time." />
        ) : (
          <FlatList
            ref={listRef}
            data={lines}
            keyExtractor={i => String(i.id)}
            onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: false })}
            renderItem={({ item }) => (
              <View style={{ paddingVertical: 4, borderBottomColor: 'rgba(0,230,118,0.06)', borderBottomWidth: 1 }}>
                <Text style={{ color: C.dim2, fontSize: 9 }}>{item.ts}</Text>
                <Text style={{ color: colorFor(item.level), fontSize: 11.5, lineHeight: 16 }}>{item.msg}</Text>
              </View>
            )}
          />
        )}
      </Card>
      <GlassButton title="CLEAR VIEW" onPress={() => setLines([])} style={{ marginTop: 10 }} />
    </View>
  );
}
