import logging
import numpy as np
import torch
from torch import nn
from torch.serialization import load
from tqdm import tqdm
from torch import optim
from torch.nn import functional as F
from torch.utils.data import DataLoader
from utils.inc_net import SimpleCosineIncrementalNet, SimpleVitNet
from models.base import BaseLearner
from utils.toolkit import target2onehot, tensor2numpy

import wandb

num_workers = 8
import timeit

class Learner(BaseLearner):
    def __init__(self, args):
        super().__init__(args)
        self._network = SimpleVitNet(args, True)
        self.args=args
        self.batch_size = self.args["batch_size"]

    def after_task(self):
        if self.args["dataset"] == "5datasets":
            self._known_classes = 0
        else:
            self._known_classes = self._total_classes
    
    def replace_fc(self, trainloader, model, args):
        model = model.eval()
        embedding_list = []
        label_list = []
        with torch.no_grad():
            for i, batch in enumerate(trainloader):
                (_,data,label)=batch
                data=data.cuda()
                label=label.cuda()
                embedding=model.convnet(data)["features"]
                embedding_list.append(embedding.cpu())
                label_list.append(label.cpu())
        embedding_list = torch.cat(embedding_list, dim=0)
        label_list = torch.cat(label_list, dim=0)

        class_list=np.unique(self.train_dataset.labels)
        proto_list = []
        for class_index in class_list:
            # print('Replacing...',class_index)
            data_index=(label_list==class_index).nonzero().squeeze(-1)
            embedding=embedding_list[data_index]
            proto=embedding.mean(0)
            self._network.fc.weight.data[class_index]=proto
        return model

   
    def incremental_train(self, data_manager):
        self._cur_task += 1
        self._total_classes = self._known_classes + data_manager.get_task_size(self._cur_task)
        self._network.update_fc(self._total_classes)
        logging.info("Learning on {}-{}".format(self._known_classes, self._total_classes))

        train_dataset = data_manager.get_dataset(np.arange(self._known_classes, self._total_classes),
                                                 source="train", mode="train",
                                                 subset=self.args["subset"], ratio=self.args["subset_per"])
        self.train_dataset=train_dataset
        self.data_manager=data_manager
        self.train_loader = DataLoader(train_dataset, batch_size=self.args["batch_size"], shuffle=True,
                                       num_workers=num_workers)
        test_dataset = data_manager.get_dataset(np.arange(0, self._total_classes),
                                                source="test", mode="test",
                                                subset=False)
        self.test_loader = DataLoader(test_dataset, batch_size=self.args["batch_size"],
                                      shuffle=False, num_workers=num_workers)

        train_dataset_for_protonet=data_manager.get_dataset(np.arange(self._known_classes,
                                                            self._total_classes),
                                                            source="train", mode="test",
                                                            subset = self.args["subset"], ratio = self.args["subset_per"])
        self.train_loader_for_protonet = DataLoader(train_dataset_for_protonet,
                                                    batch_size=self.args["batch_size"], shuffle=True,
                                                    num_workers=num_workers)

        if len(self._multiple_gpus) > 1:
            print('Multiple GPUs')
            self._network = nn.DataParallel(self._network, self._multiple_gpus)
        self._train(self.train_loader, self.test_loader, self.train_loader_for_protonet)
        if len(self._multiple_gpus) > 1:
            self._network = self._network.module

    def _train(self, train_loader, test_loader, train_loader_for_protonet):
        self._network.to(self._device)
        self.replace_fc(train_loader_for_protonet, self._network, None)

    def computer_FLOPS(self):
        from ptflops import get_model_complexity_info
        import re

        with torch.cuda.device(0):
            # Model thats already available
            net = self._network.convnet
            macs, params_ = get_model_complexity_info(net, (3, 224, 224), as_strings=True,
                                                      print_per_layer_stat=False, verbose=True)
            # Extract the numerical value
            flops = eval(re.findall(r'([\d.]+)', macs)[0]) * 2
            # Extract the unit
            flops_unit = re.findall(r'([A-Za-z]+)', macs)[0][0]

            print('Computational complexity: {:<8}'.format(macs))
            print('Computational complexity: {} {}Flops'.format(flops, flops_unit))
            print('Number of parameters: {:<8}'.format(params_))
            wandb.log({"FLOPS": flops})

    def profile(self):
        inputs = torch.randn(self.batch_size, 3, 224, 224)
        from torch.profiler import profile, record_function, ProfilerActivity
        with profile(activities=[ProfilerActivity.CUDA], record_shapes=True) as prof:
            with record_function("model_inference"):
                self._network.convnet.cuda()
                self._network.convnet(inputs.cuda())

        print(prof.key_averages().table(sort_by="cuda_time_total"))
        cuda_time = prof.key_averages().table(sort_by="cuda_time_total")[8939:]
        wandb.log({"Time(CUDA)": cuda_time[22:-3]})

    def evaluate_adapt_inference(self):
        loader = self.test_loader
        _, inputs, targets = next(iter(loader))

        times = []
        for i in range(5):
            start = timeit.default_timer()
            self._network.convnet(inputs.cuda())
            stop = timeit.default_timer()
            t = stop - start
            times.append(t)
        t = np.array(times).mean()
        return wandb.log({"Execution time per TTA": t})
    

   