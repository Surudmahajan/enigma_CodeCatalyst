import type { Facility, MaterialSummary, PropertyDefinition } from '@symbio/shared-types';
import { DISPOSITIONS, FREQUENCIES, UNITS, resourceSchema, splitList } from '@symbio/validation';
import { router } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Alert, Switch, Text, View } from 'react-native';

import { SelectField, StepHeader } from '@/components/domain';
import { Body, Button, Card, Chip, KeyValue, Notice, Screen, TextField } from '@/components/ui';
import { errorMessage } from '@/lib/api';
import { addDays, formatDate, formatQuantity, statusLabel, today } from '@/lib/format';
import { useClassify, useCreateResource, useFacilities, useMaterials, useProperties } from '@/lib/queries';
import { pickDocument, type PickedFile, uploadDocument } from '@/lib/upload';
import { spacing, useColors } from '@/theme';

type PropertyRow = { key: string; value: string };
const TOTAL = 9;

/**
 * Multi-step resource creation (spec §46): what → how much → where → when →
 * properties → processing → document → review → publish.
 */
export default function NewResource() {
  const c = useColors();
  const [step, setStep] = useState(1);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [materialQuery, setMaterialQuery] = useState('');
  const materials = useMaterials(materialQuery);
  const allMaterials = useMaterials('');
  const facilities = useFacilities();
  const properties = useProperties();
  const classify = useClassify();
  const create = useCreateResource();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [material, setMaterial] = useState<MaterialSummary | null>(null);
  const [quantity, setQuantity] = useState('');
  const [unit, setUnit] = useState<(typeof UNITS)[number]>('tonne');
  const [frequency, setFrequency] = useState<(typeof FREQUENCIES)[number]>('MONTH');
  const [facility, setFacility] = useState<Facility | null>(null);
  const [start, setStart] = useState(today());
  const [end, setEnd] = useState(addDays(365));
  const [rows, setRows] = useState<PropertyRow[]>([]);
  const [processingRequired, setProcessingRequired] = useState(false);
  const [processingTypes, setProcessingTypes] = useState('');
  const [disposition, setDisposition] = useState<(typeof DISPOSITIONS)[number]>('DISPOSAL');
  const [disposalCost, setDisposalCost] = useState('');
  const [askingPrice, setAskingPrice] = useState('');
  const [file, setFile] = useState<PickedFile | null>(null);

  useEffect(() => {
    if (!facility && facilities.data?.length) setFacility(facilities.data[0]);
  }, [facilities.data, facility]);

  const propertyByKey = useMemo(() => new Map((properties.data ?? []).map((p) => [p.key, p])), [properties.data]);

  const form = {
    name, description, material_id: material?.id ?? null, quantity, unit, frequency, facility_id: facility?.id ?? '',
    window_start: start, window_end: end, processing_required: processingRequired, processing_types: processingTypes,
    current_disposition: disposition, disposal_cost_per_unit: disposalCost, asking_price_per_unit: askingPrice,
  };
  const STEP_FIELDS: Record<number, string[]> = { 1: ['name'], 2: ['quantity'], 3: ['facility_id'],
    4: ['window_start', 'window_end'], 6: ['disposal_cost_per_unit', 'asking_price_per_unit'] };

  const next = () => {
    const result = resourceSchema.safeParse(form);
    const fieldErrors: Record<string, string> = {};
    if (!result.success) {
      result.error.issues.forEach((i) => { fieldErrors[String(i.path[0])] ??= i.message; });
    }
    if (step === 5) rows.forEach((r, i) => { if (!r.key || r.value.trim() === '' || Number.isNaN(Number(r.value))) fieldErrors[`row${i}`] = 'Choose a property and enter a number'; });
    const relevant = Object.fromEntries(Object.entries(fieldErrors).filter(([k]) =>
      (STEP_FIELDS[step] ?? []).includes(k) || (step === 5 && k.startsWith('row'))));
    setErrors(relevant);
    if (!Object.keys(relevant).length) setStep((s) => Math.min(TOTAL, s + 1));
  };

  const submit = async (publish: boolean) => {
    try {
      const resource = await create.mutateAsync({
        facility_id: facility!.id, currency: 'INR', material_id: material?.id ?? null, name: name.trim(), description: description || null,
        quantity_available: quantity, unit, frequency, availability_start: start, availability_end: end || null,
        physical_state: material?.physical_state ?? 'SOLID', processing_required: processingRequired,
        processing_types: splitList(processingTypes), current_disposition: disposition,
        disposal_cost_per_unit: disposalCost || null, asking_price_per_unit: askingPrice || null,
        properties: rows.map((r) => ({ property_key: r.key, value_numeric: r.value })), publish,
      });
      if (file) await uploadDocument(file, { resource_id: resource.id }).catch((e) => Alert.alert('Document not uploaded', errorMessage(e)));
      Alert.alert(publish ? 'Resource published' : 'Draft saved',
        publish ? 'SYMBIO is now matching it against active requirements.' : 'Publish it when you are ready.');
      router.replace(`/resource/${resource.id}`);
    } catch (e) {
      Alert.alert('Could not save the resource', errorMessage(e));
    }
  };

  const suggest = () => {
    if ((name + description).trim().length < 3) return;
    classify.mutate(`${name}. ${description}`);
  };

  return (
    <Screen>
      {step === 1 ? (
        <>
          <StepHeader step={1} total={TOTAL} title="What do you have?" subtitle="Name it the way your plant does — we'll help normalize it." />
          <TextField label="Name" value={name} onChangeText={setName} placeholder="e.g. BOF steel slag" error={errors.name} />
          <TextField label="Description (optional)" value={description} onChangeText={setDescription} multiline
            placeholder="Origin, condition, how it is generated…" />
          <SelectField label="Normalized material" value={material} options={materials.data ?? allMaterials.data ?? []}
            onChange={setMaterial} getKey={(m) => m.id} getLabel={(m) => `${m.canonical_name} · ${m.category}`}
            placeholder="Search the material catalogue" hint="Matching uses the normalized material, its properties and applications." />
          <TextField label="Filter catalogue" value={materialQuery} onChangeText={setMaterialQuery} placeholder="slag, ash, sludge…" />
          <Button title="Suggest material from my description" variant="secondary" icon="sparkles-outline" onPress={suggest}
            loading={classify.isPending} />
          {classify.data?.suggestions.length ? (
            <Card style={{ marginTop: spacing.md }}>
              <Body muted>Suggestions (tap to use — nothing is applied automatically):</Body>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.sm }}>
                {classify.data.suggestions.map((s) => (
                  <Chip key={s.material.id} label={`${s.material.canonical_name} ${Math.round(s.confidence * 100)}%`}
                    selected={material?.id === s.material.id} onPress={() => setMaterial(s.material)} />
                ))}
              </View>
            </Card>
          ) : null}
        </>
      ) : null}

      {step === 2 ? (
        <>
          <StepHeader step={2} total={TOTAL} title="How much?" subtitle="Partial matches are fine — demand does not need to equal supply." />
          <TextField label="Quantity" value={quantity} onChangeText={setQuantity} keyboardType="decimal-pad" error={errors.quantity} />
          <Text style={{ color: c.text, fontWeight: '600', marginBottom: spacing.sm }}>Unit</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.lg }}>
            {UNITS.map((u) => <Chip key={u} label={u} selected={unit === u} onPress={() => setUnit(u)} />)}
          </View>
          <Text style={{ color: c.text, fontWeight: '600', marginBottom: spacing.sm }}>Frequency</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
            {FREQUENCIES.map((f) => <Chip key={f} label={f === 'ONE_TIME' ? 'One-time lot' : `Per ${f.toLowerCase()}`}
              selected={frequency === f} onPress={() => setFrequency(f)} />)}
          </View>
        </>
      ) : null}

      {step === 3 ? (
        <>
          <StepHeader step={3} total={TOTAL} title="Where?" subtitle="Distance drives logistics, cost and emission estimates." />
          <SelectField label="Facility" value={facility} options={facilities.data ?? []} onChange={setFacility} searchable={false}
            getKey={(f) => f.id} getLabel={(f) => `${f.name} · ${f.location.city}`} />
          {errors.facility_id ? <Notice tone="danger">{errors.facility_id}</Notice> : null}
          <Notice>Other organizations only see the city until you accept a connection.</Notice>
        </>
      ) : null}

      {step === 4 ? (
        <>
          <StepHeader step={4} total={TOTAL} title="When is it available?" subtitle="Listings expire automatically after the end date." />
          <TextField label="Available from (YYYY-MM-DD)" value={start} onChangeText={setStart} error={errors.window_start} />
          <TextField label="Available until (YYYY-MM-DD, blank = open-ended)" value={end} onChangeText={setEnd} error={errors.window_end} />
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
            <Chip label="6 months" onPress={() => setEnd(addDays(182))} />
            <Chip label="1 year" onPress={() => setEnd(addDays(365))} />
            <Chip label="2 years" onPress={() => setEnd(addDays(730))} />
            <Chip label="Open-ended" onPress={() => setEnd('')} />
          </View>
        </>
      ) : null}

      {step === 5 ? (
        <>
          <StepHeader step={5} total={TOTAL} title="What are its properties?"
            subtitle="Measured values let demanders' technical constraints be checked — this is how hidden matches are found." />
          {rows.map((row, i) => (
            <Card key={i}>
              <SelectField<PropertyDefinition> label="Property" value={propertyByKey.get(row.key) ?? null}
                options={properties.data ?? []} getKey={(p) => p.key} getLabel={(p) => `${p.name}${p.unit ? ` (${p.unit})` : ''}`}
                onChange={(p) => setRows(rows.map((r, j) => (j === i ? { ...r, key: p?.key ?? '' } : r)))} />
              <TextField label="Measured value" value={row.value} keyboardType="decimal-pad" error={errors[`row${i}`]}
                onChangeText={(v) => setRows(rows.map((r, j) => (j === i ? { ...r, value: v } : r)))} />
              <Button title="Remove" variant="ghost" onPress={() => setRows(rows.filter((_, j) => j !== i))} />
            </Card>
          ))}
          <Button title="Add property" icon="add" variant="secondary" onPress={() => setRows([...rows, { key: '', value: '' }])} />
          <Notice>You can also upload a test report in step 7 and let SYMBIO extract values for you to confirm.</Notice>
        </>
      ) : null}

      {step === 6 ? (
        <>
          <StepHeader step={6} total={TOTAL} title="Does it require processing?" subtitle="Processing doesn't rule out a match; it changes feasibility." />
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.lg }}>
            <Body>Processing required before use</Body>
            <Switch value={processingRequired} onValueChange={setProcessingRequired} accessibilityLabel="Processing required" />
          </View>
          {processingRequired ? (
            <TextField label="Processing steps (comma separated)" value={processingTypes} onChangeText={setProcessingTypes}
              placeholder="crushing, drying" />
          ) : null}
          <Text style={{ color: c.text, fontWeight: '600', marginBottom: spacing.sm }}>What happens to it today?</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.lg }}>
            {DISPOSITIONS.map((d) => <Chip key={d} label={statusLabel(d)} selected={disposition === d} onPress={() => setDisposition(d)} />)}
          </View>
          <TextField label="Current disposal cost per unit (optional)" value={disposalCost} onChangeText={setDisposalCost}
            keyboardType="decimal-pad" error={errors.disposal_cost_per_unit} hint="Used only to estimate savings; hidden from others until you connect." />
          <TextField label="Asking price per unit (optional)" value={askingPrice} onChangeText={setAskingPrice}
            keyboardType="decimal-pad" error={errors.asking_price_per_unit} />
        </>
      ) : null}

      {step === 7 ? (
        <>
          <StepHeader step={7} total={TOTAL} title="Supporting document" subtitle="Specification sheet, test report, certificate or photo (optional)." />
          {file ? <Card><KeyValue icon="document-attach-outline" label={file.name} value={`${Math.round((file.size ?? 0) / 1024)} KB`} /></Card> : null}
          <Button title={file ? 'Choose a different file' : 'Choose file'} icon="attach" variant="secondary"
            onPress={async () => setFile(await pickDocument())} />
          <Notice>Documents are private: only your organization and connected counterparts can open them.</Notice>
        </>
      ) : null}

      {step === 8 ? (
        <>
          <StepHeader step={8} total={TOTAL} title="Review" />
          <Card>
            <KeyValue label="Name" value={name} />
            <KeyValue label="Material" value={material?.canonical_name ?? 'Not normalized'} />
            <KeyValue label="Quantity" value={formatQuantity(quantity || 0, unit, frequency)} />
            <KeyValue label="Facility" value={facility?.name ?? '—'} />
            <KeyValue label="Window" value={`${formatDate(start)} → ${formatDate(end || null)}`} />
            <KeyValue label="Properties" value={String(rows.length)} />
            <KeyValue label="Processing" value={processingRequired ? processingTypes || 'Required' : 'Direct use'} />
            <KeyValue label="Today" value={statusLabel(disposition)} />
            <KeyValue label="Document" value={file?.name ?? 'None'} />
          </Card>
          {!material ? <Notice tone="warning">Without a normalized material, matching relies on application and text similarity only.</Notice> : null}
        </>
      ) : null}

      {step === 9 ? (
        <>
          <StepHeader step={9} total={TOTAL} title="Publish" subtitle="Publishing adds it to the common database and starts matching." />
          <Button title="Publish resource" icon="rocket-outline" onPress={() => submit(true)} loading={create.isPending} />
          <View style={{ height: spacing.md }} />
          <Button title="Save as draft" variant="secondary" onPress={() => submit(false)} disabled={create.isPending} />
        </>
      ) : null}

      <View style={{ flexDirection: 'row', gap: spacing.md, marginTop: spacing.xl }}>
        {step > 1 ? <Button title="Back" variant="secondary" onPress={() => setStep(step - 1)} style={{ flex: 1 }} /> : null}
        {step < TOTAL ? <Button title="Next" onPress={next} style={{ flex: 1 }} /> : null}
      </View>
    </Screen>
  );
}
