import os
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms

transform = transforms.Compose([
    transforms.Resize((112,112)),
    transforms.ToTensor()
])

class FaceDataset(Dataset):
    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.images = []
        self.labels = []
        for i, identity in enumerate(os.listdir(root_dir)):
            identity_path = os.path.join(root_dir, identity)
            for img_name in os.listdir(identity_path):
                self.images.append(os.path.join(identity_path, img_name))
                self.labels.append(i)
    
    def __len__(self):
        return len(self.images)
    
    def __getitem__(self, idx):
        img = Image.open(self.images[idx]).convert('RGB')
        img = transform(img)
        label = self.labels[idx]
        return img, label
