import { zodResolver } from '@hookform/resolvers/zod';
import { brand } from '@symbio/config';
import type { AuthResponse } from '@symbio/shared-types';
import { loginSchema, type LoginForm } from '@symbio/validation';
import { Link, router } from 'expo-router';
import { useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { KeyboardAvoidingView, Platform, Text, View } from 'react-native';

import { Body, Button, Notice, Screen, TextField } from '@/components/ui';
import { api, errorMessage } from '@/lib/api';
import { useAuth } from '@/lib/auth-store';
import { fontSize, spacing, useColors } from '@/theme';

export default function Login() {
  const c = useColors();
  const signIn = useAuth((s) => s.signIn);
  const [error, setError] = useState<string>();
  const { control, handleSubmit, formState } = useForm<LoginForm>({ resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' } });

  const onSubmit = handleSubmit(async (values) => {
    setError(undefined);
    try {
      await signIn(await api.post<AuthResponse>('/auth/login', values, false));
      router.replace('/');
    } catch (e) {
      setError(errorMessage(e));
    }
  });

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen>
        <View style={{ marginTop: spacing.xxl * 1.5, marginBottom: spacing.xxl }}>
          <Text style={{ color: c.accent, fontSize: fontSize.xxl + 6, fontWeight: '900', letterSpacing: 4 }}>{brand.name}</Text>
          <Body muted style={{ marginTop: spacing.sm }}>{brand.tagline}</Body>
        </View>
        {error ? <Notice tone="danger">{error}</Notice> : null}
        <Controller control={control} name="email" render={({ field }) => (
          <TextField label="Work email" value={field.value} onChangeText={field.onChange} onBlur={field.onBlur}
            autoCapitalize="none" keyboardType="email-address" autoComplete="email" textContentType="username"
            error={formState.errors.email?.message} />
        )} />
        <Controller control={control} name="password" render={({ field }) => (
          <TextField label="Password" value={field.value} onChangeText={field.onChange} onBlur={field.onBlur}
            secureTextEntry autoComplete="password" textContentType="password" error={formState.errors.password?.message} />
        )} />
        <Button title="Sign in" onPress={onSubmit} loading={formState.isSubmitting} />
        <View style={{ marginTop: spacing.xl, alignItems: 'center' }}>
          <Link href="/register"><Text style={{ color: c.info, fontSize: fontSize.md }}>New to SYMBIO? Create an account</Text></Link>
        </View>
      </Screen>
    </KeyboardAvoidingView>
  );
}
