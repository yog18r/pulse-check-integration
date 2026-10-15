/**
 * The translator for the React tree.
 *
 * React note: a *context* hands a value to every component below a
 * provider without passing it through each component's props. The card
 * and the editor each provide the translator for the user's language at
 * their root; any component reads it with `useT()`. Outside a provider
 * (some unit tests) it is English.
 */
import { createContext, useContext } from 'react';
import { EN, type Translator } from '../i18n';

export const I18nContext = createContext<Translator>(EN);

export function useT(): Translator {
  return useContext(I18nContext);
}
