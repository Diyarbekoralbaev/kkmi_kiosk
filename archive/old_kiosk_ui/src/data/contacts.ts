export type ContactIcon = 'emergency' | 'building' | 'phone'

export interface Contact {
  id: string
  icon: ContactIcon
  labelKk: string
  subtitleKk?: string
  phone: string
  emergency?: boolean
}

export const CONTACTS: Contact[] = [
  {
    id: 'emergency_112',
    icon: 'emergency',
    labelKk: 'Yagona favqulodda',
    subtitleKk: 'Hámme xızmetler ushın',
    phone: '112',
    emergency: true,
  },
  {
    id: 'fire_101',
    icon: 'emergency',
    labelKk: 'Ot óshiriw xızmeti',
    subtitleKk: 'Órt, qutqarıw',
    phone: '101',
    emergency: true,
  },
  {
    id: 'police_102',
    icon: 'emergency',
    labelKk: 'Militsiya',
    subtitleKk: 'Huqıq buzılıwı',
    phone: '102',
    emergency: true,
  },
  {
    id: 'medic_103',
    icon: 'emergency',
    labelKk: 'Tez járdem',
    subtitleKk: 'Medicinа járdem',
    phone: '103',
    emergency: true,
  },
  {
    id: 'hakim_reception',
    icon: 'building',
    labelKk: 'Hákim qabılxanası',
    subtitleKk: 'Ulıwma máseleler',
    phone: '+998 61 222 00 00',
  },
  {
    id: 'hakim_press',
    icon: 'building',
    labelKk: 'Press-xızmet',
    subtitleKk: 'BAQ hám jańalıqlar',
    phone: '+998 61 222 11 22',
  },
]
