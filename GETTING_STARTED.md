# Adaptiv Controller – Controller-in-a-box: Getting Started

_Last updated: 2025-12-11_

This guide is written for a **single developer** who has purchased the Adaptiv Controller – GitHub MCP Server as a controller-in-a-box. The goal is to take you from a .zip file to a running MCP server on Render, connected to your own custom controller in ChatGPT.

You do not need to be a DevOps expert. You do need:

- A GitHub account.
- A Render.com account.
- Access to ChatGPT with MCP / custom GPT support.

---

## 1. Unpack the product and create your repo

1. Save the product bundle you received (for example `adaptiv-controller-v1.0.0.zip`).
2. Unzip it on your machine.
3. Create a new **private** repository in your own GitHub account (for example `my-adaptiv-controller`).
4. Initialize the repo and push the unzipped contents:
   - `git init`
   - `git remote add origin git@github.com:<your-username>/<your-repo>.git`
   - `git add .`
   - `git commit -m "Initial commit from Adaptiv Controller bundle"`
   - `git push -u origin main`

From this point on, you own the repo and can customize it as you like for your own use.
