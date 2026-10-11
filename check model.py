from ultralytics import YOLO

# This is the model your bot is using
model_path = r"best.pt"

model = YOLO(model_path)
print("Classes in YOUR BOT'S model:")
for idx, name in model.names.items():
    print(f"   {idx}: {name}")