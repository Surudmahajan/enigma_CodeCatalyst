import { zodResolver } from '@hookform/resolvers/zod';
import type { AuthResponse } from '@symbio/shared-types';
import { registerSchema, type RegisterForm } from '@symbio/validation';
import { Link, router } from 'expo-router';
import { useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { KeyboardAvoidingView, Platform, Text, View } from 'react-native';

import { Button, Notice, Screen, TextField, Title } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { useAuth } from '@/lib/auth-store';
import { fontSize, spacing, useColors } from '@/theme';

export default function Register() {
  const c = useColors();
  const signIn = useAuth((s) => s.signIn);
  const [error, setError] = useState<string>();
  const { control, handleSubmit, formState } = useForm<RegisterForm>({
    resolver: zodResolver(registerSchema), defaultValues: { first_name: '', last_name: '', email: '', password: '' },
  });

  const onSubmit = handleSubmit(async (values) => {
    setError(undefined);
    try {
      await signIn(await api.post<AuthResponse>('/auth/register', values, false));
      router.replace('/onboarding');
    } catch (e) {
      setError(errorMessage(e));
    }
  });

  const field = (name: keyof RegisterForm, label: string, extra: object = {}) => (
    <Controller control={control} name={name} render={({ field: f }) => (
      <TextField label={label} value={f.value} onChangeText={f.onChange} onBlur={f.onBlur}
        error={formState.errors[name]?.message} {...extra} />
    )} />
  );

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen>
        <View style={{ height: spacing.xxl }} />
        <Title sub="Your personal account. You'll set up or join your organization next.">Create account</Title>
        {error ? <Notice tone="danger">{error}</Notice> : null}
        <View style={{ flexDirection: 'row', gap: spacing.md }}>
          <View style={{ flex: 1 }}>{field('first_name', 'First name', { autoComplete: 'given-name' })}</View>
          <View style={{ flex: 1 }}>{field('last_name', 'Last name', { autoComplete: 'family-name' })}</View>
        </View>
        {field('email', 'Work email', { autoCapitalize: 'none', keyboardType: 'email-address', autoComplete: 'email' })}
        {field('password', 'Password', { secureTextEntry: true, autoComplete: 'new-password',
          hint: 'At least 10 characters with a letter and a number.' })}
        <Button title="Create account" onPress={onSubmit} loading={formState.isSubmitting} />
        <View style={{ marginTop: spacing.xl, alignItems: 'center' }}>
          <Link href="/login"><Text style={{ color: c.info, fontSize: fontSize.md }}>Already registered? Sign in</Text></Link>
        </View>
      </Screen>
    </KeyboardAvoidingView>
  );
}
