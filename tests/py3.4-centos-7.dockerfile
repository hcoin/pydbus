FROM centos:7
RUN yum makecache fast
RUN rpm -Uvh http://download.fedoraproject.org/pub/epel/7/x86_64/e/epel-release-7-10.noarch.rpm


RUN yum -y update
RUN yum -y upgrade

RUN yum install -y dbus psmisc dbus-x11 python34  python34-pip  python34-devel  pygobject3 pygobject3-devel
RUN python3.4 --version

RUN pip3.4 install --upgrade pip
RUN pip3.4 install greenlet

ADD . /root/
RUN rpm --upgrade /root/repos/3.4/*
RUN cd /root && python3.4 setup.py install

RUN /root/tests/run.sh python3.4
