import { Ionicons } from '@expo/vector-icons';
import { zodResolver } from '@hookform/resolvers/zod';
import { organizationSchema, type OrganizationForm } from '@symbio/validation';
import { Redirect, router } from 'expo-router';
import { useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { Pressable, Text, View } from 'react-native';

import { StepHeader } from '@/components/domain';
import { Body, Button, Chip, Notice, Screen, TextField } from '@/components/ui';
import { errorMessage } from '@/lib/api';
import { useAuth, type ViewMode } from '@/lib/auth-store';
import { useCreateOrganization } from '@/lib/queries';
import { fontSize, radius, spacing, useColors } from '@/theme';

const SECTORS = ['Steel manufacturing', 'Cement', 'Construction', 'Power generation', 'Chemicals', 'Food processing',
  'Pulp & paper', 'Textiles', 'Building materials', 'Mining & quarrying', 'Renewable energy', 'Foundry'];

type Mode = 'PROVIDER' | 'DEMANDER' | 'BOTH';
const MODES: { value: Mode; title: string; text: string; icon: React.ComponentProps<typeof Ionicons>['name'] }[] = [
  { value: 'PROVIDER', title: 'Provider', text: 'We have by-products or surplus resources. Who can use them?', icon: 'arrow-up-circle-outline' },
  { value: 'DEMANDER', title: 'Demander', text: 'We need materials. Who can supply them from their by-products?', icon: 'arrow-down-circle-outline' },
  { value: 'BOTH', title: 'Both', text: 'We provide some resources and need others.', icon: 'swap-vertical-outline' },
];

/** Register → organization profile → select Provider / Demander / Both. */
export default function Onboarding() {
  const c = useColors();
  const { status, reloadMe, setOrganization, setViewMode } = useAuth();
  const create = useCreateOrganization();
  const [step, setStep] = useState(1);
  const [mode, setMode] = useState<Mode>('BOTH');
  const [error, setError] = useState<string>();
  const { control, handleSubmit, formState, trigger, setValue, watch } = useForm<OrganizationForm>({
    resolver: zodResolver(organizationSchema),
    defaultValues: { display_name: '', legal_name: '', industry_sector: '', description: '', city: '', state: '',
      country: 'India', latitude: '', longitude: '' },
  });
  if (status === 'signedOut') return <Redirect href="/login" />;

  const text = (name: keyof OrganizationForm, label: string, extra: object = {}) => (
    <Controller control={control} name={name} render={({ field }) => (
      <TextField label={label} value={field.value ?? ''} onChangeText={field.onChange} onBlur={field.onBlur}
        error={formState.errors[name]?.message} {...extra} />
    )} />
  );

  const submit = handleSubmit(async (v) => {
    setError(undefined);
    try {
      const org = await create.mutateAsync({
        display_name: v.display_name, legal_name: v.legal_name, industry_sector: v.industry_sector,
        description: v.description || null, operating_mode: mode,
        headquarters: { city: v.city, state: v.state || null, country: v.country,
          latitude: v.latitude ? v.latitude : null, longitude: v.longitude ? v.longitude : null },
      });
      await reloadMe();
      await setOrganization(org.id);
      setViewMode((mode === 'BOTH' ? 'PROVIDER' : mode) as ViewMode);
      router.replace('/(tabs)');
    } catch (e) {
      setError(errorMessage(e));
    }
  });

  return (
    <Screen>
      {step === 1 ? (
        <>
          <StepHeader step={1} total={3} title="Organization profile"
            subtitle="Other organizations see your display name, sector and city. Contacts stay private until you connect." />
          {text('display_name', 'Display name', { placeholder: 'e.g. ABC Steel' })}
          {text('legal_name', 'Registered legal name')}
          {text('industry_sector', 'Industry sector')}
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.lg }}>
            {SECTORS.map((s) => (
              <Chip key={s} label={s} selected={watch('industry_sector') === s}
                onPress={() => setValue('industry_sector', s, { shouldValidate: true })} />
            ))}
          </View>
          {text('description', 'What does your organization do? (optional)', { multiline: true })}
          <Button title="Continue" onPress={async () => (await trigger(['display_name', 'legal_name', 'industry_sector'])) && setStep(2)} />
        </>
      ) : null}
      {step === 2 ? (
        <>
          <StepHeader step={2} total={3} title="Main facility location"
            subtitle="Used to estimate logistics. Exact coordinates are only shared after a connection is accepted." />
          {text('city', 'City / industrial area')}
          {text('state', 'State / region')}
          {text('country', 'Country')}
          <View style={{ flexDirection: 'row', gap: spacing.md }}>
            <View style={{ flex: 1 }}>{text('latitude', 'Latitude', { keyboardType: 'numeric', placeholder: '18.74' })}</View>
            <View style={{ flex: 1 }}>{text('longitude', 'Longitude', { keyboardType: 'numeric', placeholder: '73.82' })}</View>
          </View>
          <Notice>Coordinates enable distance, transport cost and emission estimates. Without them those factors are marked "not assessed".</Notice>
          <Button title="Continue" onPress={async () => (await trigger(['city', 'country', 'latitude', 'longitude'])) && setStep(3)} />
          <Button title="Back" variant="ghost" onPress={() => setStep(1)} />
        </>
      ) : null}
      {step === 3 ? (
        <>
          <StepHeader step={3} total={3} title="How will you use SYMBIO?"
            subtitle="This sets up your workspace. You can switch later — an organization can always be both." />
          {error ? <Notice tone="danger">{error}</Notice> : null}
          {MODES.map((m) => (
            <Pressable key={m.value} onPress={() => setMode(m.value)} accessibilityRole="radio" accessibilityState={{ checked: mode === m.value }}
              style={{ borderWidth: 2, borderColor: mode === m.value ? c.accent : c.border, borderRadius: radius.lg,
                padding: spacing.lg, marginBottom: spacing.md, backgroundColor: c.surface, flexDirection: 'row', gap: spacing.md }}>
              <Ionicons name={m.icon} size={28} color={mode === m.value ? c.accent : c.textMuted} />
              <View style={{ flex: 1 }}>
                <Text style={{ color: c.text, fontSize: fontSize.lg, fontWeight: '700' }}>{m.title}</Text>
                <Body muted>{m.text}</Body>
              </View>
            </Pressable>
          ))}
          <Button title="Create organization" onPress={submit} loading={create.isPending} />
          <Button title="Back" variant="ghost" onPress={() => setStep(2)} />
        </>
      ) : null}
    </Screen>
  );
}
