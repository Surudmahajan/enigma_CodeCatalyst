/**
 * SYMBIO UI kit: large touch targets, clear hierarchy, explicit states
 * (loading, empty, error, offline, expired) so no screen only handles the happy path.
 */
import { Ionicons } from '@expo/vector-icons';
import type { ComponentProps, ReactNode } from 'react';
import { useEffect, useRef } from 'react';
import {
  ActivityIndicator,
  Animated,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  type TextInputProps,
  View,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { statusLabel } from '@/lib/format';
import { useIsOnline } from '@/lib/network';
import { fontSize, radius, spacing, touchTarget, useColors } from '@/theme';

export type IconName = ComponentProps<typeof Ionicons>['name'];

export function Screen({ children, scroll = true, refreshing, onRefresh, padded = true }: {
  children: ReactNode; scroll?: boolean; refreshing?: boolean; onRefresh?: () => void; padded?: boolean;
}) {
  const c = useColors();
  const content = scroll ? (
    <ScrollView
      contentContainerStyle={[padded && styles.padded, { paddingBottom: spacing.xxl * 2 }]}
      keyboardShouldPersistTaps="handled"
      refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} /> : undefined}>
      {children}
    </ScrollView>
  ) : (
    <View style={[{ flex: 1 }, padded && styles.padded]}>{children}</View>
  );
  return (
    <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: c.background }}>
      <OfflineBanner />
      {content}
    </SafeAreaView>
  );
}

export function OfflineBanner() {
  const online = useIsOnline();
  const c = useColors();
  if (online) return null;
  return (
    <View style={[styles.banner, { backgroundColor: c.warningSoft }]} accessibilityRole="alert">
      <Ionicons name="cloud-offline-outline" size={16} color={c.warning} />
      <Text style={{ color: c.warning, fontSize: fontSize.sm, flex: 1 }}>
        You're offline. Showing saved data; changes will sync when your connection returns.
      </Text>
    </View>
  );
}

export function Title({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  const c = useColors();
  return (
    <View style={{ marginBottom: spacing.lg }}>
      <Text style={{ color: c.text, fontSize: fontSize.xxl, fontWeight: '700' }}>{children}</Text>
      {sub ? <Text style={{ color: c.textMuted, fontSize: fontSize.md, marginTop: spacing.xs }}>{sub}</Text> : null}
    </View>
  );
}

export function SectionHeader({ title, action }: { title: string; action?: ReactNode }) {
  const c = useColors();
  return (
    <View style={styles.sectionHeader}>
      <Text style={{ color: c.textMuted, fontSize: fontSize.sm, fontWeight: '700', letterSpacing: 0.6 }}>
        {title.toUpperCase()}
      </Text>
      {action}
    </View>
  );
}

export function Body({ children, muted, style }: { children: ReactNode; muted?: boolean; style?: object }) {
  const c = useColors();
  return <Text style={[{ color: muted ? c.textMuted : c.text, fontSize: fontSize.md, lineHeight: 22 }, style]}>{children}</Text>;
}

export function Card({ children, onPress, style, accessibilityLabel }: {
  children: ReactNode; onPress?: () => void; style?: ViewStyle; accessibilityLabel?: string;
}) {
  const c = useColors();
  const base = [styles.card, { backgroundColor: c.surface, borderColor: c.border }, style];
  if (!onPress) return <View style={base}>{children}</View>;
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={accessibilityLabel}
      style={({ pressed }) => [...base, pressed && { opacity: 0.85 }]}>
      {children}
    </Pressable>
  );
}

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';

export function Button({ title, onPress, variant = 'primary', loading, disabled, icon, style }: {
  title: string; onPress: () => void; variant?: ButtonVariant; loading?: boolean; disabled?: boolean;
  icon?: IconName; style?: ViewStyle;
}) {
  const c = useColors();
  const palette: Record<ButtonVariant, { bg: string; fg: string; border: string }> = {
    primary: { bg: c.primary, fg: c.onPrimary, border: c.primary },
    secondary: { bg: c.surface, fg: c.text, border: c.border },
    danger: { bg: c.dangerSoft, fg: c.danger, border: c.dangerSoft },
    ghost: { bg: 'transparent', fg: c.info, border: 'transparent' },
  };
  const p = palette[variant];
  const inactive = disabled || loading;
  return (
    <Pressable
      onPress={onPress}
      disabled={inactive}
      accessibilityRole="button"
      accessibilityState={{ disabled: inactive, busy: loading }}
      style={({ pressed }) => [styles.button, { backgroundColor: p.bg, borderColor: p.border },
        inactive && { opacity: 0.55 }, pressed && { opacity: 0.8 }, style]}>
      {loading ? <ActivityIndicator color={p.fg} /> : (
        <>
          {icon ? <Ionicons name={icon} size={18} color={p.fg} /> : null}
          <Text style={{ color: p.fg, fontSize: fontSize.md, fontWeight: '600' }}>{title}</Text>
        </>
      )}
    </Pressable>
  );
}

export function TextField({ label, error, hint, ...props }: TextInputProps & { label: string; error?: string; hint?: string }) {
  const c = useColors();
  return (
    <View style={{ marginBottom: spacing.md }}>
      <Text style={{ color: c.text, fontSize: fontSize.sm, fontWeight: '600', marginBottom: spacing.xs }}>{label}</Text>
      <TextInput
        placeholderTextColor={c.textMuted}
        accessibilityLabel={label}
        {...props}
        style={[styles.input, { color: c.text, backgroundColor: c.surface, borderColor: error ? c.danger : c.border },
          props.multiline && { minHeight: 96, textAlignVertical: 'top' }]}
      />
      {error ? <Text style={{ color: c.danger, fontSize: fontSize.sm, marginTop: spacing.xs }}>{error}</Text>
        : hint ? <Text style={{ color: c.textMuted, fontSize: fontSize.sm, marginTop: spacing.xs }}>{hint}</Text> : null}
    </View>
  );
}

export function Chip({ label, selected, onPress, tone }: {
  label: string; selected?: boolean; onPress?: () => void; tone?: 'accent' | 'warning' | 'danger' | 'info' | 'hidden';
}) {
  const c = useColors();
  const toneColors = tone ? { accent: [c.accentSoft, c.accent], warning: [c.warningSoft, c.warning],
    danger: [c.dangerSoft, c.danger], info: [c.infoSoft, c.info], hidden: [c.hiddenSoft, c.hidden] }[tone] : null;
  const bg = selected ? c.primary : toneColors ? toneColors[0] : c.surfaceMuted;
  const fg = selected ? c.onPrimary : toneColors ? toneColors[1] : c.text;
  const content = <Text style={{ color: fg, fontSize: fontSize.sm, fontWeight: '600' }}>{label}</Text>;
  if (!onPress) return <View style={[styles.chip, { backgroundColor: bg }]}>{content}</View>;
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityState={{ selected }}
      style={[styles.chip, styles.chipPressable, { backgroundColor: bg }]}>
      {content}
    </Pressable>
  );
}

const STATUS_TONE: Record<string, 'accent' | 'warning' | 'danger' | 'info' | undefined> = {
  ACTIVE: 'accent', CONNECTED: 'accent', NEGOTIATING: 'accent', ACTIVE_EXCHANGE: 'accent', COMPLETED: 'accent',
  ACCEPTED: 'accent', IN_PROGRESS: 'accent', DISCOVERED: 'info', VIEWED: 'info', INTERESTED: 'info', PLANNED: 'info',
  CONNECTION_REQUESTED: 'warning', PENDING: 'warning', PAUSED: 'warning', DRAFT: 'warning',
  REJECTED: 'danger', EXPIRED: 'danger', CANCELLED: 'danger', FAILED: 'danger', REVOKED: 'danger', ARCHIVED: undefined,
};

export function StatusBadge({ status }: { status: string }) {
  return <Chip label={statusLabel(status)} tone={STATUS_TONE[status]} />;
}

export function Segmented<T extends string>({ options, value, onChange }: {
  options: { value: T; label: string }[]; value: T; onChange: (v: T) => void;
}) {
  const c = useColors();
  return (
    <View style={[styles.segmented, { backgroundColor: c.surfaceMuted }]} accessibilityRole="tablist">
      {options.map((o) => (
        <Pressable key={o.value} onPress={() => onChange(o.value)} accessibilityRole="tab"
          accessibilityState={{ selected: o.value === value }}
          style={[styles.segment, o.value === value && { backgroundColor: c.surface }]}>
          <Text style={{ color: o.value === value ? c.text : c.textMuted, fontWeight: '600' }}>{o.label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

export function ScoreRing({ score, size = 64 }: { score: number; size?: number }) {
  const c = useColors();
  const pct = Math.round(score * 100);
  const color = score >= 0.75 ? c.accent : score >= 0.5 ? c.warning : c.danger;
  return (
    <View accessibilityLabel={`Opportunity score ${pct} out of 100`}
      style={{ width: size, height: size, borderRadius: size / 2, borderWidth: 5, borderColor: color,
        alignItems: 'center', justifyContent: 'center' }}>
      <Text style={{ color: c.text, fontWeight: '800', fontSize: size / 3.4 }}>{pct}</Text>
    </View>
  );
}

export function Bar({ value }: { value: number | null | undefined }) {
  const c = useColors();
  const color = value === null || value === undefined ? c.border
    : value >= 0.75 ? c.accent : value >= 0.5 ? c.warning : c.danger;
  return (
    <View style={[styles.bar, { backgroundColor: c.surfaceMuted }]}>
      <View style={{ width: `${Math.round((value ?? 0) * 100)}%`, backgroundColor: color, height: '100%', borderRadius: 4 }} />
    </View>
  );
}

export function KeyValue({ label, value, icon }: { label: string; value: ReactNode; icon?: IconName }) {
  const c = useColors();
  return (
    <View style={styles.kv}>
      {icon ? <Ionicons name={icon} size={18} color={c.textMuted} style={{ marginRight: spacing.sm }} /> : null}
      <Text style={{ color: c.textMuted, fontSize: fontSize.sm, flex: 1 }}>{label}</Text>
      <Text style={{ color: c.text, fontSize: fontSize.md, fontWeight: '600', flexShrink: 1, textAlign: 'right' }}>{value}</Text>
    </View>
  );
}

export function Stat({ label, value, icon, onPress }: { label: string; value: string | number; icon: IconName; onPress?: () => void }) {
  const c = useColors();
  return (
    <Card onPress={onPress} style={{ flex: 1, minWidth: '45%' }} accessibilityLabel={`${label}: ${value}`}>
      <Ionicons name={icon} size={20} color={c.accent} />
      <Text style={{ color: c.text, fontSize: fontSize.xxl, fontWeight: '800', marginTop: spacing.sm }}>{value}</Text>
      <Text style={{ color: c.textMuted, fontSize: fontSize.sm }}>{label}</Text>
    </Card>
  );
}

export function Notice({ tone = 'info', children, icon }: { tone?: 'info' | 'warning' | 'danger' | 'accent'; children: ReactNode; icon?: IconName }) {
  const c = useColors();
  const [bg, fg] = { info: [c.infoSoft, c.info], warning: [c.warningSoft, c.warning], danger: [c.dangerSoft, c.danger],
    accent: [c.accentSoft, c.accent] }[tone];
  return (
    <View style={[styles.notice, { backgroundColor: bg }]}>
      <Ionicons name={icon ?? (tone === 'danger' ? 'alert-circle-outline' : 'information-circle-outline')} size={18} color={fg} />
      <Text style={{ color: fg, flex: 1, fontSize: fontSize.sm, lineHeight: 20 }}>{children}</Text>
    </View>
  );
}

// --- States -------------------------------------------------------------------------------------

export function Skeleton({ height = 88, count = 3 }: { height?: number; count?: number }) {
  const c = useColors();
  const opacity = useRef(new Animated.Value(0.5)).current;
  useEffect(() => {
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(opacity, { toValue: 1, duration: 700, useNativeDriver: true }),
      Animated.timing(opacity, { toValue: 0.5, duration: 700, useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [opacity]);
  return (
    <View accessibilityLabel="Loading" accessibilityRole="progressbar">
      {Array.from({ length: count }).map((_, i) => (
        <Animated.View key={i} style={{ height, borderRadius: radius.md, backgroundColor: c.surfaceMuted, marginBottom: spacing.md, opacity }} />
      ))}
    </View>
  );
}

export function EmptyState({ icon, title, message, action }: { icon: IconName; title: string; message?: string; action?: ReactNode }) {
  const c = useColors();
  return (
    <View style={styles.centerState}>
      <Ionicons name={icon} size={40} color={c.textMuted} />
      <Text style={{ color: c.text, fontSize: fontSize.lg, fontWeight: '700', marginTop: spacing.md, textAlign: 'center' }}>{title}</Text>
      {message ? <Body muted style={{ textAlign: 'center', marginTop: spacing.xs }}>{message}</Body> : null}
      {action ? <View style={{ marginTop: spacing.lg, alignSelf: 'stretch' }}>{action}</View> : null}
    </View>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <EmptyState icon="warning-outline" title="Something went wrong" message={message}
      action={onRetry ? <Button title="Try again" variant="secondary" onPress={onRetry} icon="refresh" /> : undefined} />
  );
}

/** Standard loading / error / content switch for a query. */
export function QueryState({ query, children, skeleton }: {
  query: { isLoading: boolean; isError: boolean; error: unknown; refetch: () => unknown };
  children: ReactNode; skeleton?: ReactNode;
}) {
  if (query.isLoading) return <>{skeleton ?? <Skeleton />}</>;
  if (query.isError) {
    const message = query.error instanceof Error ? query.error.message : 'Please try again.';
    return <ErrorState message={message} onRetry={() => query.refetch()} />;
  }
  return <>{children}</>;
}

const styles = StyleSheet.create({
  padded: { padding: spacing.lg },
  banner: { flexDirection: 'row', gap: spacing.sm, alignItems: 'center', paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: spacing.xl, marginBottom: spacing.sm },
  card: { borderWidth: 1, borderRadius: radius.lg, padding: spacing.lg, marginBottom: spacing.md },
  button: { minHeight: touchTarget, borderRadius: radius.md, borderWidth: 1, paddingHorizontal: spacing.lg,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm },
  input: { minHeight: touchTarget, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: spacing.md, fontSize: fontSize.md },
  chip: { paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill, alignSelf: 'flex-start' },
  chipPressable: { minHeight: 36, justifyContent: 'center' },
  segmented: { flexDirection: 'row', borderRadius: radius.md, padding: 4, marginBottom: spacing.lg },
  segment: { flex: 1, minHeight: 40, alignItems: 'center', justifyContent: 'center', borderRadius: radius.sm },
  bar: { height: 8, borderRadius: 4, overflow: 'hidden', flex: 1 },
  kv: { flexDirection: 'row', alignItems: 'center', paddingVertical: spacing.sm, gap: spacing.sm },
  notice: { flexDirection: 'row', gap: spacing.sm, padding: spacing.md, borderRadius: radius.md, marginBottom: spacing.md },
  centerState: { alignItems: 'center', paddingVertical: spacing.xxl, paddingHorizontal: spacing.lg },
});
