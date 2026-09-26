import { darkColors, fontSize, lightColors, radius, spacing, touchTarget, type ColorTokens } from '@symbio/config';
import { useColorScheme } from 'react-native';

export { fontSize, radius, spacing, touchTarget };
export type { ColorTokens };

export function useColors(): ColorTokens {
  return useColorScheme() === 'dark' ? darkColors : lightColors;
}
