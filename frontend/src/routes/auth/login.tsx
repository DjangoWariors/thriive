import {useState, useEffect} from 'react';
import {useNavigate} from 'react-router';
import {useForm} from 'react-hook-form';
import {zodResolver} from '@hookform/resolvers/zod';
import {z} from 'zod';
import {Mail, Lock, Eye, EyeOff} from 'lucide-react';
import axios from 'axios';
import {useAuth} from '../../hooks/useAuth';
import {authService} from '../../services/auth';
import {Button} from '../../components/ui/Button';
import {Input} from '../../components/ui/Input';
import {notify} from '../../utils/notify';
import {cn} from '../../utils/cn';


const passwordSchema = z.object({
    identifier: z.string().min(1, 'Email or mobile is required'),
    password: z.string().min(1, 'Password is required'),
});

const otpRequestSchema = z.object({
    identifier: z.string().min(1, 'Email or mobile is required'),
});

const otpVerifySchema = z.object({
    otp: z
        .string()
        .length(6, 'OTP must be exactly 6 digits')
        .regex(/^\d{6}$/, 'OTP must be numeric'),
});

type PasswordFormValues = z.infer<typeof passwordSchema>;
type OTPRequestFormValues = z.infer<typeof otpRequestSchema>;
type OTPVerifyFormValues = z.infer<typeof otpVerifySchema>;


function maskIdentifier(id: string): string {
    if (id.includes('@')) {
        const [local = '', domain = ''] = id.split('@');
        return `${local.slice(0, 2)}***@${domain}`;
    }
    if (id.length > 6) {
        return `${id.slice(0, 2)}****${id.slice(-4)}`;
    }
    return id;
}

function apiErrorMessage(err: unknown): string {
    if (axios.isAxiosError(err)) {
        if (!err.response) return 'Unable to connect.';
        const status = err.response.status;
        if (status === 401) return 'Invalid email or password.';
        if (status === 423) return 'Account locked. Try again later.';
        if (status === 429) return 'Too many requests.';
    }
    return 'Something went wrong.';
}


type Tab = 'password' | 'otp';
type OTPStep = 'request' | 'verify';

export default function Login() {
    const [tab, setTab] = useState<Tab>('password');
    const [showPassword, setShowPassword] = useState(false);
    const [otpStep, setOtpStep] = useState<OTPStep>('request');
    const [otpIdentifier, setOtpIdentifier] = useState('');
    const [apiError, setApiError] = useState<string | null>(null);

    const {login, loginOTP, isAuthenticated} = useAuth();
    const navigate = useNavigate();

    useEffect(() => {
        if (isAuthenticated) {
            void navigate('/', {replace: true});
        }
    }, [isAuthenticated, navigate]);

    const passwordForm = useForm<PasswordFormValues>({
        resolver: zodResolver(passwordSchema),
    });

    const otpRequestForm = useForm<OTPRequestFormValues>({
        resolver: zodResolver(otpRequestSchema),
    });

    const otpVerifyForm = useForm<OTPVerifyFormValues>({
        resolver: zodResolver(otpVerifySchema),
    });

    function handleTabChange(next: Tab) {
        setTab(next);
        setApiError(null);
        setOtpStep('request');
    }

    async function onPasswordSubmit(values: PasswordFormValues) {
        setApiError(null);
        try {
            await login(values.identifier, values.password);
            notify.success('Welcome back!');
            void navigate('/', {replace: true});
        } catch (err) {
            setApiError(apiErrorMessage(err));
        }
    }

    async function onOTPRequest(values: OTPRequestFormValues) {
        setApiError(null);
        try {
            await authService.requestOTP(values.identifier);
            setOtpIdentifier(values.identifier);
            setOtpStep('verify');
        } catch (err) {
            setApiError(apiErrorMessage(err));
        }
    }

    async function onOTPVerify(values: OTPVerifyFormValues) {
        setApiError(null);
        try {
            await loginOTP(otpIdentifier, values.otp);
            notify.success('Welcome back!');
            void navigate('/', {replace: true});
        } catch (err) {
            setApiError(apiErrorMessage(err));
        }
    }

    function handleChangeNumber() {
        setOtpStep('request');
        setOtpIdentifier('');
        otpVerifyForm.reset();
        setApiError(null);
    }

    return (
        <div
            className="min-h-screen bg-gradient-to-br from-primary-dark via-primary to-primary-light flex items-center justify-center p-4">
            <div className="w-full max-w-md">


                <div className="relative rounded-t-2xl bg-primary px-8 py-6 text-center">

                    <div className="mb-2 flex items-center justify-center gap-2">
                        <span className="text-3xl leading-none">🚀</span>
                        <span className="text-3xl font-bold text-white">Thriive</span>
                    </div>
                    <p className="text-xs font-medium uppercase tracking-widest text-white/80">
                        Sales Incentive Management Platform
                    </p>
                </div>


                <div className="rounded-b-2xl bg-white px-8 py-6 shadow-xl">
                    <div className="mb-6">
                        <h2 className="text-xl font-semibold text-gray-900">Welcome back 👋</h2>
                        <p className="mt-1 text-sm text-gray-500">
                            Sign in to manage incentives, targets &amp; performance
                        </p>
                    </div>


                    <div className="mb-6 flex rounded-lg bg-gray-100 p-1">
                        {(['password', 'otp'] as const).map((t) => (
                            <button
                                key={t}
                                type="button"
                                onClick={() => handleTabChange(t)}
                                className={cn(
                                    'flex-1 rounded-md py-1.5 text-sm font-medium transition-all',
                                    tab === t
                                        ? 'bg-white text-gray-900 shadow'
                                        : 'text-gray-500 hover:text-gray-700',
                                )}
                            >
                                {t === 'password' ? 'Password' : 'OTP'}
                            </button>
                        ))}
                    </div>


                    {apiError !== null && (
                        <div className="mb-4 rounded-lg border border-danger-100 bg-danger-50 px-4 py-3 text-sm text-danger">
                            {apiError}
                        </div>
                    )}


                    {tab === 'password' && (
                        <form
                            onSubmit={passwordForm.handleSubmit(onPasswordSubmit)}
                            noValidate
                            className="space-y-4"
                        >
                            <Input
                                label="Email or Mobile"
                                placeholder="you@company.com"
                                autoComplete="username"
                                leftIcon={<Mail size={16}/>}
                                error={passwordForm.formState.errors.identifier?.message}
                                {...passwordForm.register('identifier')}
                            />

                            <Input
                                label="Password"
                                type={showPassword ? 'text' : 'password'}
                                placeholder="••••••••"
                                autoComplete="current-password"
                                leftIcon={<Lock size={16}/>}
                                rightIcon={
                                    <button
                                        type="button"
                                        onClick={() => setShowPassword((v) => !v)}
                                        aria-label={showPassword ? 'Hide password' : 'Show password'}
                                        tabIndex={-1}
                                        className="text-gray-400 hover:text-gray-600 focus:outline-none"
                                    >
                                        {showPassword ? <EyeOff size={16}/> : <Eye size={16}/>}
                                    </button>
                                }
                                error={passwordForm.formState.errors.password?.message}
                                {...passwordForm.register('password')}
                            />

                            <div className="flex items-center justify-between">
                                <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-600">
                                    <input
                                        type="checkbox"
                                        className="h-4 w-4 rounded border-gray-300 text-primary"
                                    />
                                    Remember me for 7 days
                                </label>
                                <button
                                    type="button"
                                    className="text-sm font-medium text-primary hover:text-primary-dark"
                                >
                                    Forgot password?
                                </button>
                            </div>

                            <Button
                                type="submit"
                                fullWidth
                                size="lg"
                                loading={passwordForm.formState.isSubmitting}
                            >
                                Sign In →
                            </Button>
                        </form>
                    )}


                    {tab === 'otp' && otpStep === 'request' && (
                        <form
                            onSubmit={otpRequestForm.handleSubmit(onOTPRequest)}
                            noValidate
                            className="space-y-4"
                        >
                            <Input
                                label="Email or Mobile"
                                placeholder="you@company.com"
                                autoComplete="username"
                                leftIcon={<Mail size={16}/>}
                                error={otpRequestForm.formState.errors.identifier?.message}
                                {...otpRequestForm.register('identifier')}
                            />

                            <Button
                                type="submit"
                                fullWidth
                                size="lg"
                                loading={otpRequestForm.formState.isSubmitting}
                            >
                                Send OTP
                            </Button>
                        </form>
                    )}


                    {tab === 'otp' && otpStep === 'verify' && (
                        <form
                            onSubmit={otpVerifyForm.handleSubmit(onOTPVerify)}
                            noValidate
                            className="space-y-4"
                        >
                            <p className="text-center text-sm text-gray-600">
                                OTP sent to{' '}
                                <span className="font-medium text-gray-900">
                  {maskIdentifier(otpIdentifier)}
                </span>
                            </p>

                            <Input
                                label="Enter OTP"
                                placeholder="······"
                                type="text"
                                inputMode="numeric"
                                maxLength={6}
                                autoComplete="one-time-code"
                                className="text-center tracking-[0.4em] text-lg"
                                error={otpVerifyForm.formState.errors.otp?.message}
                                {...otpVerifyForm.register('otp')}
                            />

                            <Button
                                type="submit"
                                fullWidth
                                size="lg"
                                loading={otpVerifyForm.formState.isSubmitting}
                            >
                                Verify &amp; Sign In
                            </Button>

                            <button
                                type="button"
                                onClick={handleChangeNumber}
                                className="w-full text-sm text-gray-500 hover:text-gray-700"
                            >
                                ← Change number
                            </button>
                        </form>
                    )}


                    <p className="mt-8 text-center text-xs text-gray-400">
                        © 2026 Thriive IMS · Powered by CraziBrain · All rights reserved.
                    </p>
                </div>
            </div>
        </div>
    );
}
