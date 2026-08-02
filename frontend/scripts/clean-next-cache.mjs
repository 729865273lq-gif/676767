import { rmSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const packageJsonPath = resolve(process.cwd(), "package.json");
const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf8"));

if (packageJson.name !== "foreign-trade-web") {
  throw new Error("Refusing to clean .next outside the foreign-trade-web package.");
}

rmSync(resolve(process.cwd(), ".next"), { recursive: true, force: true });
