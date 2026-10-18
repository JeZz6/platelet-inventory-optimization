# Publish this project to GitHub

The repository files are prepared. Publication still requires access to your GitHub account and a target repository. No account credentials are included in this package.

## Recommended: GitHub Desktop

1. Extract this ZIP. The folder containing README.md is the repository root.
2. Sign in to GitHub Desktop.
3. Choose File > Add local repository and select this folder. If Desktop reports it is not a Git repository, use the offered create-a-repository option in this same directory. Avoid creating a second nested project folder.
4. Review the file list, enter `Add verified Guan reference project`, and commit if the initial files are not already committed.
5. Click Publish repository. Use `platelet-inventory-optimization` as the name. Choose visibility intentionally; keeping it private initially is suitable for team review.
6. Open the repository on GitHub. Confirm the README, data, results and `.github/workflows/ci.yml` are present.
7. Open Actions and inspect the completed checks. Do not claim a hosted check passed until it has run there.

## Alternative: Git command line

Create a new **empty** repository on GitHub. Do not initialize it with a README, license or gitignore, because this folder already supplies project files.

Open a terminal in the extracted project folder, then run:

```bash
git init -b main
git add .
git status
git commit -m "Add verified Guan reference project"
git remote add origin https://github.com/YOUR-USERNAME/platelet-inventory-optimization.git
git push -u origin main
```

Replace `YOUR-USERNAME` with the actual repository owner. Sign in through your configured Git authentication or credential manager. If Git requests an author name/email, configure your own identity; do not use someone else's details.

## Browser upload

Create a repository, then use Add file > Upload files. Upload the **contents** of the extracted folder, including `.github`, `.gitignore`, `.gitattributes` and `.python-version`, rather than uploading only the ZIP. Check that hidden entries were not omitted by the file selector. The initial package is below GitHub's 100-files-per-upload limit; an individual browser-uploaded file must be below 25 MiB.

## After publication

- Download a fresh copy and follow README.md to reproduce the pipeline.
- Use Settings > Collaborators to invite teammates if desired.
- Keep new policy experiments separate from the published reference results.
- The repository holds runnable research code. An interactive Python web application is a separate deliverable; GitHub Pages can display static project material but cannot serve this Python backend.

Official instructions:
- https://docs.github.com/en/desktop/adding-and-cloning-repositories/adding-an-existing-project-to-github-using-github-desktop
- https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github
- https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository

