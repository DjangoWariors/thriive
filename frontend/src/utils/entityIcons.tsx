import {
    Award, Box, Briefcase, Building, Building2, Car, Circle, Crown, Droplet,
    Factory, Gift, GitBranch, Globe, Hammer, Handshake, HardHat, Home, Landmark,
    Layers, MapPin, Network, Package, Paintbrush, Pill, Plug, ShoppingBag,
    ShoppingCart, Stethoscope, Store, Target, Tractor, Truck, User, UserCog,
    Users, Warehouse, Wheat, Wrench, Zap,
    type LucideIcon,
} from 'lucide-react';


export const ENTITY_ICONS: {name: string; Icon: LucideIcon}[] = [
    {name: 'store', Icon: Store},
    {name: 'building', Icon: Building},
    {name: 'building-2', Icon: Building2},
    {name: 'factory', Icon: Factory},
    {name: 'warehouse', Icon: Warehouse},
    {name: 'landmark', Icon: Landmark},
    {name: 'home', Icon: Home},
    {name: 'truck', Icon: Truck},
    {name: 'package', Icon: Package},
    {name: 'box', Icon: Box},
    {name: 'shopping-cart', Icon: ShoppingCart},
    {name: 'shopping-bag', Icon: ShoppingBag},
    {name: 'user', Icon: User},
    {name: 'users', Icon: Users},
    {name: 'user-cog', Icon: UserCog},
    {name: 'briefcase', Icon: Briefcase},
    {name: 'hard-hat', Icon: HardHat},
    {name: 'wrench', Icon: Wrench},
    {name: 'hammer', Icon: Hammer},
    {name: 'paintbrush', Icon: Paintbrush},
    {name: 'plug', Icon: Plug},
    {name: 'zap', Icon: Zap},
    {name: 'droplet', Icon: Droplet},
    {name: 'pill', Icon: Pill},
    {name: 'stethoscope', Icon: Stethoscope},
    {name: 'car', Icon: Car},
    {name: 'tractor', Icon: Tractor},
    {name: 'wheat', Icon: Wheat},
    {name: 'handshake', Icon: Handshake},
    {name: 'award', Icon: Award},
    {name: 'gift', Icon: Gift},
    {name: 'crown', Icon: Crown},
    {name: 'target', Icon: Target},
    {name: 'layers', Icon: Layers},
    {name: 'network', Icon: Network},
    {name: 'git-branch', Icon: GitBranch},
    {name: 'map-pin', Icon: MapPin},
    {name: 'globe', Icon: Globe},
];

const ICON_MAP = new Map(ENTITY_ICONS.map((e) => [e.name, e.Icon]));

/** Resolve a stored icon name to a component, falling back to a neutral dot. */
export function resolveIcon(name?: string | null): LucideIcon {
    return (name && ICON_MAP.get(name)) || Circle;
}

/** Render a stored entity-type icon by name. */
export function EntityIcon({name, className}: {name?: string | null; className?: string}) {
    const Icon = resolveIcon(name);
    return <Icon className={className}/>;
}
