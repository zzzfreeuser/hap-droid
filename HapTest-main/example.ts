import * as fs from "fs";

function imageToDataUrl(imagePath: string): string {
    if (!fs.existsSync(imagePath) || !fs.statSync(imagePath).isFile()) {
        throw new Error("Image file not found: " + imagePath);
    }

    const imageData = fs.readFileSync(imagePath);
    const base64Encoded = imageData.toString("base64");

    return "data:image/png;base64," + base64Encoded;
}

console.log(
  imageToDataUrl("D:\\GithubProjects\\hap-droid\\out\\shui_llm_converted\\2026-04-13-17-38-05\\temp\\screenCap_201340601677.png")
); 