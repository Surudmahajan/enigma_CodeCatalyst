import { FREQUENCIES, UNITS, exchangeSchema } from '@symbio/validation';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Alert, Text, View } from 'react-native';

import { Button, Chip, Notice, QueryState, Screen, TextField, Title } from '@/components/ui';
import { errorMessage } from '@/lib/api';
import { addDays, today } from '@/lib/format';
import { useCreateExchange, useMatch } from '@/lib/queries';
import { spacing, useColors } from '@/theme';

/** Record the terms both parties agreed in the private channel. */
export default function NewExchange() {
  const { matchId } = useLocalSearchParams<{ matchId: string }>();
  const c = useColors();
  const match = useMatch(matchId);
  const create = useCreateExchange(matchId);
  const [quantity, setQuantity] = useState('');
  const [unit, setUnit] = useState<(typeof UNITS)[number]>('tonne');
  const [frequency, setFrequency] = useState<(typeof FREQUENCIES)[number]>('MONTH');
  const [price, setPrice] = useState('');
  const [start, setStart] = useState(addDays(7));
  const [end, setEnd] = useState(addDays(187));
  const [notes, setNotes] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const req = match.data?.requirement;
    if (req && !quantity) {
      setQuantity(String(Math.min(Number(req.quantity), Number(match.data!.resource.quantity))));
      setUnit(req.unit as (typeof UNITS)[number]);
      setFrequency(req.frequency as (typeof FREQUENCIES)[number]);
    }
  }, [match.data, quantity]);

  const submit = async () => {
    const values = { agreed_quantity: quantity, unit, agreed_frequency: frequency, agreed_price_per_unit: price,
      start_date: start, end_date: end, notes };
    const parsed = exchangeSchema.safeParse(values);
    if (!parsed.success) {
      const e: Record<string, string> = {};
      parsed.error.issues.forEach((i) => { e[String(i.path[0])] ??= i.message; });
      return setErrors(e);
    }
    if (end && end < start) return setErrors({ end_date: 'End date must be on or after the start date' });
    try {
      const exchange = await create.mutateAsync({ agreed_quantity: quantity, unit, agreed_frequency: frequency,
        agreed_price_per_unit: price || null, currency: 'INR', start_date: start, end_date: end || null,
        notes: notes || null, delivery_terms: {} });
      router.replace(`/exchange/${exchange.id}`);
    } catch (e) {
      Alert.alert('Could not record the exchange', errorMessage(e));
    }
  };

  return (
    <Screen>
      <Title sub="Captures the agreement; the status then tracks delivery through to completion.">Agreed exchange</Title>
      <QueryState query={match}>
        {match.data ? <Notice>{match.data.resource.name} → {match.data.requirement.name}</Notice> : null}
      </QueryState>
      <TextField label="Agreed quantity" value={quantity} onChangeText={setQuantity} keyboardType="decimal-pad" error={errors.agreed_quantity} />
      <Text style={{ color: c.text, fontWeight: '600', marginBottom: spacing.sm }}>Unit</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.md }}>
        {UNITS.map((u) => <Chip key={u} label={u} selected={unit === u} onPress={() => setUnit(u)} />)}
      </View>
      <Text style={{ color: c.text, fontWeight: '600', marginBottom: spacing.sm }}>Frequency</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.md }}>
        {FREQUENCIES.map((f) => <Chip key={f} label={f === 'ONE_TIME' ? 'One-time' : `Per ${f.toLowerCase()}`}
          selected={frequency === f} onPress={() => setFrequency(f)} />)}
      </View>
      <TextField label="Agreed price per unit, INR (optional)" value={price} onChangeText={setPrice} keyboardType="decimal-pad"
        error={errors.agreed_price_per_unit} />
      <TextField label="Start date (YYYY-MM-DD)" value={start} onChangeText={setStart} error={errors.start_date} />
      <TextField label="End date (YYYY-MM-DD, optional)" value={end} onChangeText={setEnd} error={errors.end_date}
        hint={`Today is ${today()}`} />
      <TextField label="Notes (optional)" value={notes} onChangeText={setNotes} multiline />
      <Button title="Record exchange" icon="checkmark-done" onPress={submit} loading={create.isPending} />
    </Screen>
  );
}
