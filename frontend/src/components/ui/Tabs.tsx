import { cn } from '../../utils/cn';

interface Tab {
  label: string;
  value: string;
}

interface TabsProps {
  tabs: Tab[];
  activeTab: string;
  onChange: (value: string) => void;
  className?: string;
}

export function Tabs({ tabs, activeTab, onChange, className }: TabsProps) {
  return (
    <div className={cn('border-b border-gray-200', className)}>
      <nav className="-mb-px flex gap-1" aria-label="Tabs">
        {tabs.map((tab) => (
          <button
            key={tab.value}
            onClick={() => onChange(tab.value)}
            className={cn(
              'px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap',
              tab.value === activeTab
                ? 'border-primary text-primary'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            )}
            aria-selected={tab.value === activeTab}
            role="tab"
          >
            {tab.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
