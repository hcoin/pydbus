FROM centos:7
RUN yum makecache fast
RUN rpm -Uvh http://download.fedoraproject.org/pub/epel/7/x86_64/e/epel-release-7-10.noarch.rpm
RUN rpm -Uvh https://centos7.iuscommunity.org/ius-release.rpm

RUN yum -y update
RUN yum -y upgrade

RUN yum install -y dbus psmisc dbus-x11 python36u python36u-pip python36u-devel pygobject3 pygobject3-devel pkgconfig pcre-devel
RUN ln -sf /bin/python3.6 /usr/bin/python3
RUN ln -sf /bin/python3.6 /bin/python3
RUN python3.6 --version
RUN pip3.6 install --upgrade pip
RUN pip3.6 install greenlet
RUN alternatives --install /bin/python3 python3 /bin/python3.6 2 
#RUN alternatives --install /usr/bin/python3 upython3 /bin/python3.6 2
#RUN cp /usr/bin/python3.6 /usr/bin/python3
#RUN yum whatprovides /usr/bin/python3

ADD . /root/
RUN ls -l /usr/bin/python3
RUN rpm --upgrade --nodeps /root/repos/3.6/*rpm
RUN cd /root && python3.6 setup.py install

RUN /root/tests/run.sh python3.6
