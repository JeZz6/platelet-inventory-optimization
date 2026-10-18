"""Cross-platform entry point for the complete Guan reference pipeline."""
from pathlib import Path
import argparse, os, subprocess, sys
ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default='local_results', help='New or empty forecast directory')
    args = parser.parse_args()
    out = Path(args.output_dir)
    if not out.is_absolute():
        out = ROOT / out
    if out.exists() and any(out.iterdir()):
        parser.error('Forecast output must be empty/new. Choose another --output-dir.')
    env = os.environ.copy()
    for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        env[key] = '1'
    commands = [
        ['data_synthesis.py'],
        ['forecast_models.py', '--output-dir', str(out)],
        ['verify_advanced.py', '--output-dir', str(out)],
        ['-m', 'unittest', 'discover', '-s', 'tests', '-v'],
    ]
    for arguments in commands:
        print('Running: ' + ' '.join(arguments), flush=True)
        subprocess.run([sys.executable, *arguments], cwd=ROOT, env=env, check=True)
    print('Complete. New forecast results: ' + str(out), flush=True)
    print('Fixed-order inventory results: ' + str(ROOT / 'baseline'), flush=True)

if __name__ == '__main__':
    main()
