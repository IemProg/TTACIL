
import logging
import copy
import torch
from utils import factory
from utils.data_manager import DataManager, FiveDsets_DataManager
from utils.toolkit import count_parameters
import os

import wandb
import numpy as np
import sys
import time

def train(args):
    seed_list = copy.deepcopy(args["seed"])
    device = copy.deepcopy(args["device"])

    res_finals, res_avgs = [], []
    for seed in seed_list:
        args["seed"] = seed
        args["device"] = device
        res_final, res_avg = _train(args)
        res_finals.append(res_final)
        res_avgs.append(res_avg)

    logging.info('final accs: {}'.format(res_finals))
    logging.info('avg accs: {}'.format(res_avgs))
    wandb.log({"Final Acc": res_finals})


def _train(args):
    init_cls = 0 if args ["init_cls"] == args["increment"] else args["init_cls"]
    logs_name = "logs/{}/{}/{}/{}".format(args["model_name"],args["dataset"], init_cls, args['increment'])
    
    if not os.path.exists(logs_name):
        os.makedirs(logs_name)

    logfilename = "logs/{}/{}/{}/{}/{}_{}_{}".format(
        args["model_name"],
        args["dataset"],
        init_cls,
        args["increment"],
        args["prefix"],
        args["seed"],
        args["convnet_type"],
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(filename)s] => %(message)s",
        handlers=[
            logging.FileHandler(filename=logfilename + ".log"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    _set_random()
    _set_device(args)
    print_args(args)

    dataset_lists = {"0": ['SVHN', 'MNIST', 'CIFAR10', 'NotMNIST', 'FashionMNIST'],
                    "1": ['MNIST', 'CIFAR10', 'NotMNIST', 'FashionMNIST', 'SVHN'],
                    "2": ['CIFAR10', 'NotMNIST', 'FashionMNIST', 'SVHN', 'MNIST'],
                    "3": ['NotMNIST', 'FashionMNIST', 'SVHN', 'MNIST', 'CIFAR10'],
                    "4": ['FashionMNIST', 'SVHN', 'MNIST', 'CIFAR10', 'NotMNIST'],
                    }

    if args["dataset"] != "5datasets":
        data_manager = DataManager(
            args["dataset"],
            args["shuffle"],
            args["seed"],
            args["init_cls"],
            args["increment"],
            args=args
        )
    else:
        data_manager = FiveDsets_DataManager(
            "CIFAR10",
            args["shuffle"],
            args["seed"],
            args=args,
        )

        # default: ['SVHN', 'MNIST', 'CIFAR10', 'NotMNIST', 'FashionMNIST']
        dataset_list = dataset_lists[args["dset_variant"]]  # Get the right variant of 5 datasets benchmark
        logging.info(
            "datasets are: {}".format(dataset_list)
        )

    model = factory.get_model(args["model_name"], args)

    cnn_curve, nme_curve = {"top1": [], "top5": []}, {"top1": [], "top5": []}
    for task in range(data_manager.nb_tasks):
        logging.info("All params: {}".format(count_parameters(model._network)))
        trainable_params = count_parameters(model._network, True)
        logging.info(
            "Trainable params: {}".format(trainable_params)
        )
        wandb.log({"Trainable params": trainable_params})

        if args["dataset"] == "5datasets":
            logging.info(
                "Current task: {}".format(dataset_list[task])
            )
            data_manager = FiveDsets_DataManager(
                dataset_list[task],
                args["shuffle"],
                args["seed"],
                args=args,
            )

        begin_task = time.time()
        model.incremental_train(data_manager)
        end_task = time.time()

        logging.info("Task {} training time: {}".format(task, end_task - begin_task))
        wandb.log({"Training Time": end_task - begin_task})
        if args["evaluate_flops"]:
            model.computer_FLOPS()
            model.profile()
            model.evaluate_adapt_inference()
            sys.exit(0)

        cnn_accy, nme_accy = model.eval_task()
        model.after_task()

        if nme_accy is not None:
            logging.info("CNN: {}".format(cnn_accy["grouped"]))
            logging.info("NME: {}".format(nme_accy["grouped"]))

            cnn_curve["top1"].append(cnn_accy["top1"])
            cnn_curve["top5"].append(cnn_accy["top5"])

            wandb.log({"top1": cnn_accy["top1"]})
            wandb.log({"top5": cnn_accy["top5"]})

            nme_curve["top1"].append(nme_accy["top1"])
            nme_curve["top5"].append(nme_accy["top5"])

            wandb.log({"nme_top1": nme_curve["top1"]})
            wandb.log({"nme_top5": nme_curve["top5"]})

            logging.info("CNN top1 curve: {}".format(cnn_curve["top1"]))
            logging.info("CNN top5 curve: {}".format(cnn_curve["top5"]))
            logging.info("NME top1 curve: {}".format(nme_curve["top1"]))
            logging.info("NME top5 curve: {}\n".format(nme_curve["top5"]))

            print('Average Accuracy (CNN):', sum(cnn_curve["top1"])/len(cnn_curve["top1"]))
            print('Average Accuracy (NME):', sum(nme_curve["top1"])/len(nme_curve["top1"]))

            wandb.log({"Average Accuracy": sum(cnn_curve["top1"]) / len(cnn_curve["top1"])})
            wandb.log({"Average Accuracy(NME)": sum(nme_curve["top1"]) / len(nme_curve["top1"])})

            logging.info("Average Accuracy (CNN): {}".format(sum(cnn_curve["top1"])/len(cnn_curve["top1"])))
            logging.info("Average Accuracy (NME): {}".format(sum(nme_curve["top1"])/len(nme_curve["top1"])))
        else:
            logging.info("No NME accuracy.")
            logging.info("CNN: {}".format(cnn_accy["grouped"]))

            cnn_curve["top1"].append(cnn_accy["top1"])
            cnn_curve["top5"].append(cnn_accy["top5"])

            wandb.log({"top1": cnn_accy["top1"]})
            wandb.log({"top5": cnn_accy["top5"]})

            logging.info("CNN top1 curve: {}".format(cnn_curve["top1"]))
            logging.info("CNN top5 curve: {}\n".format(cnn_curve["top5"]))

            print('Average Accuracy (CNN):', sum(cnn_curve["top1"])/len(cnn_curve["top1"]))
            wandb.log({"Average Accuracy": sum(cnn_curve["top1"])/len(cnn_curve["top1"])})
            logging.info("Average Accuracy (CNN): {}".format(sum(cnn_curve["top1"])/len(cnn_curve["top1"])))

    return (cnn_curve['top1'][-1], np.array(cnn_curve['top1']).mean())
    
def _set_device(args):
    device_type = args["device"]
    gpus = []

    for device in device_type:
        if device_type == -1:
            device = torch.device("cpu")
        else:
            device = torch.device("cuda:{}".format(device))

        gpus.append(device)

    args["device"] = gpus


def _set_random():
    torch.manual_seed(1)
    torch.cuda.manual_seed(1)
    torch.cuda.manual_seed_all(1)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def print_args(args):
    for key, value in args.items():
        logging.info("{}: {}".format(key, value))
